import logging
import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple, Union
import openai
from openai import OpenAI

from app.config.settings import get_settings
from app.config.database import get_collection
from app.core.exceptions import AIModelException, NotFoundException, BadRequestException
from app.models.chat import ChatSession, Message, MessageRole, MessageType, Entity, EntityType
from app.models.user import User
from app.models.transaction import TransactionCategory
from app.utils.helpers import get_current_time_ist, generate_unique_id

# Get settings
settings = get_settings()

# Configure logger
logger = logging.getLogger(__name__)

# Initialize OpenAI client based on configuration
def get_llm_client():
    """Get configured LLM client (OpenAI or Azure OpenAI)"""
    if settings.AZURE_OPENAI_API_KEY and settings.AZURE_OPENAI_ENDPOINT:
        # Use Azure OpenAI
        client = OpenAI(
            api_key=settings.AZURE_OPENAI_API_KEY,
            base_url=f"{settings.AZURE_OPENAI_ENDPOINT}",
            api_version="2023-05-15"
        )
        return client
    elif settings.OPENAI_API_KEY:
        # Use OpenAI
        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        return client
    else:
        logger.error("No LLM API keys configured")
        raise AIModelException(detail="LLM service not configured")

async def create_chat_session(user_id: str, title: str, session_type: str = "general", 
                             description: Optional[str] = None, 
                             context: Optional[Dict[str, Any]] = None,
                             related_ids: Optional[Dict[str, List[str]]] = None) -> Dict[str, Any]:
    """
    Create a new AI chat session
    
    Args:
        user_id: User ID
        title: Chat session title
        session_type: Type of chat session
        description: Optional description
        context: Optional initial context
        related_ids: Optional related financial entities (goals, portfolios, accounts)
        
    Returns:
        Newly created chat session
    """
    try:
        # Verify user exists
        users_collection = await get_collection("users")
        user = await users_collection.find_one({"_id": user_id})
        if not user:
            raise NotFoundException(detail="User not found")
        
        # Prepare related IDs
        related_goal_ids = []
        related_portfolio_ids = []
        related_account_ids = []
        
        if related_ids:
            related_goal_ids = related_ids.get("goal_ids", [])
            related_portfolio_ids = related_ids.get("portfolio_ids", [])
            related_account_ids = related_ids.get("account_ids", [])
        
        # Create chat session
        chat_session = ChatSession(
            user_id=user_id,
            title=title,
            description=description,
            session_type=session_type,
            context=context or {},
            related_goal_ids=related_goal_ids,
            related_portfolio_ids=related_portfolio_ids,
            related_account_ids=related_account_ids
        )
        
        # Create system message
        await _create_system_message(chat_session.id)
        
        # Save to database
        chat_sessions_collection = await get_collection("chat_sessions")
        await chat_sessions_collection.insert_one(chat_session.dict())
        
        logger.info(f"Created new chat session: {chat_session.id}")
        
        return chat_session.dict()
    
    except Exception as e:
        if isinstance(e, NotFoundException):
            raise
        logger.error(f"Error creating chat session: {str(e)}")
        raise AIModelException(detail=f"Failed to create chat session: {str(e)}")

async def send_message(session_id: str, content: str, 
                      message_type: MessageType = MessageType.TEXT,
                      rich_content: Optional[Dict[str, Any]] = None,
                      parent_message_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Send a user message and get AI response
    
    Args:
        session_id: Chat session ID
        content: Message content
        message_type: Message type
        rich_content: Optional rich content for charts, tables, etc.
        parent_message_id: Optional parent message ID for threaded conversations
        
    Returns:
        Dictionary with user message and AI response
    """
    try:
        start_time = time.time()
        
        # Get chat session
        chat_sessions_collection = await get_collection("chat_sessions")
        chat_session = await chat_sessions_collection.find_one({"_id": session_id})
        if not chat_session:
            raise NotFoundException(detail="Chat session not found")
        
        # Get user details
        users_collection = await get_collection("users")
        user = await users_collection.find_one({"_id": chat_session["user_id"]})
        if not user:
            raise NotFoundException(detail="User not found")
        
        # Create user message
        messages_collection = await get_collection("messages")
        user_message = Message(
            session_id=session_id,
            role=MessageRole.USER,
            content=content,
            message_type=message_type,
            rich_content=rich_content,
            parent_message_id=parent_message_id
        )
        
        # Save user message
        await messages_collection.insert_one(user_message.dict())
        
        # Update session
        await chat_sessions_collection.update_one(
            {"_id": session_id},
            {
                "$set": {
                    "last_message_at": get_current_time_ist(),
                    "updated_at": get_current_time_ist()
                },
                "$inc": {"interaction_count": 1},
                "$push": {"message_ids": user_message.id}
            }
        )
        
        # Extract entities and enrich context
        entities = await extract_entities(content)
        
        # Generate AI response
        ai_response_content, metadata = await generate_ai_response(session_id, user, content, entities)
        
        # Create AI response message
        ai_response = Message(
            session_id=session_id,
            role=MessageRole.ASSISTANT,
            content=ai_response_content,
            message_type=MessageType.TEXT,
            entities=entities,
            ai_model=metadata.get("model", "gpt-4"),
            tokens_used=metadata.get("total_tokens", 0),
            processing_time=time.time() - start_time,
            parent_message_id=user_message.id
        )
        
        # Save AI response
        await messages_collection.insert_one(ai_response.dict())
        
        # Update session again
        await chat_sessions_collection.update_one(
            {"_id": session_id},
            {
                "$push": {"message_ids": ai_response.id}
            }
        )
        
        # Maybe update session summary if interaction count is a multiple of 5
        session = await chat_sessions_collection.find_one({"_id": session_id})
        if session["interaction_count"] % 5 == 0:
            summary = await generate_session_summary(session_id)
            await chat_sessions_collection.update_one(
                {"_id": session_id},
                {"$set": {"summary": summary}}
            )
        
        return {
            "user_message": user_message.dict(),
            "ai_response": ai_response.dict()
        }
    
    except Exception as e:
        if isinstance(e, NotFoundException):
            raise
        logger.error(f"Error processing message: {str(e)}")
        raise AIModelException(detail=f"Failed to process message: {str(e)}")

async def get_chat_history(session_id: str, limit: int = 20, skip: int = 0) -> List[Dict[str, Any]]:
    """
    Get chat history for a session
    
    Args:
        session_id: Chat session ID
        limit: Maximum number of messages to return
        skip: Number of messages to skip
        
    Returns:
        List of messages in chronological order
    """
    try:
        # Get chat session
        chat_sessions_collection = await get_collection("chat_sessions")
        chat_session = await chat_sessions_collection.find_one({"_id": session_id})
        if not chat_session:
            raise NotFoundException(detail="Chat session not found")
        
        # Get messages
        messages_collection = await get_collection("messages")
        messages = await messages_collection.find(
            {"session_id": session_id}
        ).sort("created_at", 1).skip(skip).limit(limit).to_list(length=limit)
        
        return messages
    
    except Exception as e:
        if isinstance(e, NotFoundException):
            raise
        logger.error(f"Error getting chat history: {str(e)}")
        raise AIModelException(detail=f"Failed to get chat history: {str(e)}")

async def analyze_spending_patterns(user_id: str, timeframe: str = "month") -> Dict[str, Any]:
    """
    Analyze user's spending patterns
    
    Args:
        user_id: User ID
        timeframe: Time period for analysis (week, month, quarter, year)
        
    Returns:
        Dictionary with spending analysis
    """
    try:
        # Get user's transactions
        transactions_collection = await get_collection("transactions")
        
        # Determine date range
        now = get_current_time_ist()
        if timeframe == "week":
            start_date = now - timedelta(days=7)
        elif timeframe == "month":
            start_date = now - timedelta(days=30)
        elif timeframe == "quarter":
            start_date = now - timedelta(days=90)
        elif timeframe == "year":
            start_date = now - timedelta(days=365)
        else:
            raise BadRequestException(detail=f"Invalid timeframe: {timeframe}")
        
        # Query transactions
        transactions = await transactions_collection.find({
            "user_id": user_id,
            "date": {"$gte": start_date},
            "transaction_type": "debit"  # Only expenses
        }).to_list(length=1000)
        
        # Group by category
        categories = {}
        for transaction in transactions:
            category = transaction.get("category", TransactionCategory.UNKNOWN)
            amount = transaction.get("amount", 0)
            
            if category in categories:
                categories[category]["total"] += amount
                categories[category]["count"] += 1
                categories[category]["transactions"].append({
                    "id": transaction["_id"],
                    "amount": amount,
                    "description": transaction.get("description", ""),
                    "date": transaction.get("date")
                })
            else:
                categories[category] = {
                    "total": amount,
                    "count": 1,
                    "transactions": [{
                        "id": transaction["_id"],
                        "amount": amount,
                        "description": transaction.get("description", ""),
                        "date": transaction.get("date")
                    }]
                }
        
        # Calculate total spending
        total_spend = sum(category["total"] for category in categories.values())
        
        # Calculate percentages
        for category in categories:
            if total_spend > 0:
                categories[category]["percentage"] = round((categories[category]["total"] / total_spend) * 100, 2)
            else:
                categories[category]["percentage"] = 0
        
        # Sort categories by total spending
        sorted_categories = sorted(
            categories.items(), 
            key=lambda x: x[1]["total"], 
            reverse=True
        )
        
        # Identify recurring expenses
        recurring_expenses = await _identify_recurring_expenses(user_id, categories)
        
        # Identify unusual spending
        unusual_spending = await _identify_unusual_spending(user_id, categories)
        
        return {
            "timeframe": timeframe,
            "start_date": start_date,
            "end_date": now,
            "total_spend": total_spend,
            "categories": dict(sorted_categories),
            "recurring_expenses": recurring_expenses,
            "unusual_spending": unusual_spending
        }
    
    except Exception as e:
        if isinstance(e, (NotFoundException, BadRequestException)):
            raise
        logger.error(f"Error analyzing spending patterns: {str(e)}")
        raise AIModelException(detail=f"Failed to analyze spending patterns: {str(e)}")

async def generate_financial_insights(user_id: str) -> Dict[str, Any]:
    """
    Generate AI-powered financial insights for user
    
    Args:
        user_id: User ID
        
    Returns:
        Dictionary with financial insights
    """
    try:
        # Get user's financial data
        user_data = await _gather_user_financial_data(user_id)
        
        # Construct prompt for insight generation
        prompt = f"""
        You are a financial advisor analyzing a user's financial data.
        Based on the following information, provide 3-5 key insights and actionable recommendations.
        
        User profile:
        - Income range: {user_data.get('income_range', 'Unknown')}
        - Risk profile: {user_data.get('risk_profile', 'Moderate')}
        
        Account summary:
        - Total balance across all accounts: ₹{user_data.get('total_balance', 0):,.2f}
        - Number of accounts: {len(user_data.get('accounts', []))}
        
        Transaction summary:
        - Monthly income: ₹{user_data.get('monthly_income', 0):,.2f}
        - Monthly expenses: ₹{user_data.get('monthly_expenses', 0):,.2f}
        - Top spending category: {user_data.get('top_spending_category', 'Unknown')}
        
        Investment summary:
        - Total investment value: ₹{user_data.get('total_investment', 0):,.2f}
        - Asset allocation: {user_data.get('asset_allocation', {})}
        
        Goals summary:
        - Number of active goals: {len(user_data.get('goals', []))}
        - Funding status: {user_data.get('goals_funding_status', 'Unknown')}
        
        Focus on practical, specific recommendations.
        """
        
        # Generate insights using AI
        client = get_llm_client()
        response = client.chat.completions.create(
            model="gpt-4" if settings.OPENAI_API_KEY else "gpt-4",
            messages=[
                {"role": "system", "content": "You are a financial advisor providing concise, actionable insights."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=1000
        )
        
        insights_text = response.choices[0].message.content
        
        # Parse insights into structured format
        insights = []
        recommendation_text = ""
        
        # Basic parsing of numbered insights
        for line in insights_text.strip().split("\n"):
            if line and (line[0].isdigit() and line[1] in [".", ")"]) or line.startswith("- "):
                insights.append(line.strip())
            else:
                recommendation_text += line.strip() + " "
        
        return {
            "insights": insights if insights else insights_text.strip().split("\n"),
            "recommendation": recommendation_text.strip(),
            "data_snapshot": {
                "timestamp": get_current_time_ist(),
                "monthly_income": user_data.get('monthly_income', 0),
                "monthly_expenses": user_data.get('monthly_expenses', 0),
                "savings_rate": user_data.get('savings_rate', 0),
                "total_balance": user_data.get('total_balance', 0),
                "total_investment": user_data.get('total_investment', 0)
            }
        }
    
    except Exception as e:
        logger.error(f"Error generating financial insights: {str(e)}")
        raise AIModelException(detail=f"Failed to generate financial insights: {str(e)}")

async def generate_financial_advice(user_id: str, question: str) -> Dict[str, Any]:
    """
    Generate personalized financial advice for a specific question
    
    Args:
        user_id: User ID
        question: User's financial question
        
    Returns:
        Dictionary with advice and supporting data
    """
    try:
        # Get user's financial data
        user_data = await _gather_user_financial_data(user_id)
        
        # Identify question topic
        topic = await _classify_financial_question(question)
        
        # Get relevant data based on topic
        relevant_data = await _get_relevant_financial_data(user_id, topic)
        
        # Construct prompt for advice generation
        prompt = f"""
        You are a financial advisor helping a user with a specific question.
        
        User question: {question}
        
        User profile:
        - Income range: {user_data.get('income_range', 'Unknown')}
        - Risk profile: {user_data.get('risk_profile', 'Moderate')}
        
        Relevant financial information:
        {json.dumps(relevant_data, indent=2)}
        
        Provide specific, actionable advice that directly addresses the user's question.
        Include relevant numbers from their financial data when appropriate.
        Be concise but thorough.
        """
        
        # Generate advice using AI
        client = get_llm_client()
        response = client.chat.completions.create(
            model="gpt-4" if settings.OPENAI_API_KEY else "gpt-4",
            messages=[
                {"role": "system", "content": "You are a financial advisor providing personalized advice."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=1000
        )
        
        advice_text = response.choices[0].message.content
        
        return {
            "question": question,
            "topic": topic,
            "advice": advice_text,
            "supporting_data": relevant_data,
            "timestamp": get_current_time_ist()
        }
    
    except Exception as e:
        logger.error(f"Error generating financial advice: {str(e)}")
        raise AIModelException(detail=f"Failed to generate financial advice: {str(e)}")

async def get_user_chat_sessions(user_id: str) -> List[Dict[str, Any]]:
    """
    Get all chat sessions for a user
    
    Args:
        user_id: User ID
        
    Returns:
        List of chat sessions
    """
    try:
        # Get chat sessions
        chat_sessions_collection = await get_collection("chat_sessions")
        chat_sessions = await chat_sessions_collection.find(
            {"user_id": user_id}
        ).sort("updated_at", -1).to_list(length=100)
        
        # For each session, get the most recent message
        messages_collection = await get_collection("messages")
        for session in chat_sessions:
            latest_message = await messages_collection.find_one(
                {"session_id": session["_id"], "role": "assistant"},
                sort=[("created_at", -1)]
            )
            if latest_message:
                session["latest_message"] = {
                    "content": latest_message["content"],
                    "created_at": latest_message["created_at"]
                }
        
        return chat_sessions
    
    except Exception as e:
        logger.error(f"Error getting user chat sessions: {str(e)}")
        raise AIModelException(detail=f"Failed to get user chat sessions: {str(e)}")

# Private helper functions
async def _create_system_message(session_id: str) -> Dict[str, Any]:
    """Create initial system message for a chat session"""
    system_prompt = """
    You are a financial advisor assistant for an AI-powered personal finance platform.
    Your primary goal is to help users understand their finances and provide personalized advice.
    
    You can:
    1. Answer questions about the user's finances and transactions
    2. Provide personalized financial advice
    3. Explain financial concepts in simple terms
    4. Offer insights on spending patterns and investment strategies
    
    Be polite, concise, and focus on actionable advice.
    Always use Indian financial context (e.g., rupees, Indian tax laws, mutual funds, PPF, etc.).
    """
    
    messages_collection = await get_collection("messages")
    system_message = Message(
        session_id=session_id,
        role=MessageRole.SYSTEM,
        content=system_prompt
    )
    
    await messages_collection.insert_one(system_message.dict())
    return system_message.dict()

async def extract_entities(content: str) -> List[Entity]:
    """Extract financial entities from text"""
    entities = []
    
    # This would typically use NLP to extract entities
    # For now, just a simple implementation
    # In a real implementation, you would use more sophisticated methods
    
    # Look for account mentions
    account_patterns = [
        r'savings account',
        r'current account',
        r'credit card',
        r'loan'
    ]
    
    for pattern in account_patterns:
        if re.search(pattern, content.lower()):
            entities.append(
                Entity(
                    id=generate_unique_id(),
                    type=EntityType.ACCOUNT,
                    name=pattern,
                    value=None
                )
            )
    
    # Look for goal mentions
    goal_patterns = [
        r'retirement',
        r'education',
        r'home',
        r'car',
        r'emergency fund'
    ]
    
    for pattern in goal_patterns:
        if re.search(pattern, content.lower()):
            entities.append(
                Entity(
                    id=generate_unique_id(),
                    type=EntityType.GOAL,
                    name=pattern,
                    value=None
                )
            )
    
    return entities

async def generate_ai_response(session_id: str, user: Dict[str, Any], 
                             user_message: str, entities: List[Entity]) -> Tuple[str, Dict[str, Any]]:
    """Generate AI response based on user message and financial context"""
    try:
        # Get chat history
        messages_collection = await get_collection("messages")
        history = await messages_collection.find(
            {"session_id": session_id}
        ).sort("created_at", 1).to_list(length=20)
        
        # Format history for API call
        formatted_history = []
        for msg in history:
            if msg["role"] == MessageRole.SYSTEM:
                formatted_history.append({"role": "system", "content": msg["content"]})
            elif msg["role"] == MessageRole.USER:
                formatted_history.append({"role": "user", "content": msg["content"]})
            elif msg["role"] == MessageRole.ASSISTANT:
                formatted_history.append({"role": "assistant", "content": msg["content"]})
        
        # Add current user message
        formatted_history.append({"role": "user", "content": user_message})
        
        # Add financial context if needed
        chat_sessions_collection = await get_collection("chat_sessions")
        chat_session = await chat_sessions_collection.find_one({"_id": session_id})
        
        # Get relevant financial data based on entities and message
        financial_context = ""
        if entities or "budget" in user_message.lower() or "spend" in user_message.lower():
            financial_data = await _get_user_financial_summary(user["_id"])
            financial_context = f"\n\nUser's financial summary: {json.dumps(financial_data, indent=2)}"
        
        # If session has specific related entities, include them
        if chat_session.get("related_goal_ids") or chat_session.get("related_portfolio_ids"):
            specific_data = await _get_specific_financial_entities(
                user["_id"],
                chat_session.get("related_goal_ids", []),
                chat_session.get("related_portfolio_ids", []),
                chat_session.get("related_account_ids", [])
            )
            if specific_data:
                financial_context += f"\n\nSpecific entities: {json.dumps(specific_data, indent=2)}"
        
        # Update last message with financial context if needed
        if financial_context:
            formatted_history[-1]["content"] += financial_context
        
        # Call OpenAI API
        client = get_llm_client()
        response = client.chat.completions.create(
            model="gpt-4" if settings.OPENAI_API_KEY else "gpt-4",
            messages=formatted_history,
            max_tokens=1000
        )
        
        return response.choices[0].message.content, {
            "model": response.model,
            "total_tokens": response.usage.total_tokens
        }
    
    except Exception as e:
        logger.error(f"Error generating AI response: {str(e)}")
        return (
            "I'm sorry, I'm having trouble processing your request right now. Please try again later.",
            {"model": "error", "total_tokens": 0}
        )

async def generate_session_summary(session_id: str) -> str:
    """Generate a summary of the chat session"""
    try:
        messages_collection = await get_collection("messages")
        messages = await messages_collection.find(
            {"session_id": session_id, "role": {"$in": ["user", "assistant"]}}
        ).sort("created_at", 1).to_list(length=100)
        
        if len(messages) < 3:
            return "Not enough messages for summary"
        
        # Create conversation transcript
        transcript = "\n".join([
            f"{msg['role'].upper()}: {msg['content']}"
            for msg in messages
        ])
        
        # Generate summary using AI
        client = get_llm_client()
        response = client.chat.completions.create(
            model="gpt-4" if settings.OPENAI_API_KEY else "gpt-4",
            messages=[
                {"role": "system", "content": "Summarize the following conversation in 1-2 sentences:"},
                {"role": "user", "content": transcript}
            ],
            max_tokens=100
        )
        
        return response.choices[0].message.content
    
    except Exception as e:
        logger.error(f"Error generating session summary: {str(e)}")
        return "Session summary unavailable"

async def _gather_user_financial_data(user_id: str) -> Dict[str, Any]:
    """Gather user's financial data for AI processing"""
    # Get user profile
    users_collection = await get_collection("users")
    user = await users_collection.find_one({"_id": user_id})
    
    if not user:
        raise NotFoundException(detail="User not found")
    
    # Get accounts
    accounts_collection = await get_collection("accounts")
    accounts = await accounts_collection.find(
        {"user_id": user_id, "status": "active"}
    ).to_list(length=100)
    
    total_balance = sum(account.get("current_balance", 0) for account in accounts)
    
    # Get transactions for last 30 days
    transactions_collection = await get_collection("transactions")
    thirty_days_ago = get_current_time_ist() - timedelta(days=30)
    transactions = await transactions_collection.find({
        "user_id": user_id,
        "date": {"$gte": thirty_days_ago}
    }).to_list(length=500)
    
    # Calculate monthly income and expenses
    monthly_income = sum(
        txn.get("amount", 0) 
        for txn in transactions 
        if txn.get("transaction_type") == "credit"
    )
    
    monthly_expenses = sum(
        txn.get("amount", 0) 
        for txn in transactions 
        if txn.get("transaction_type") == "debit"
    )
    
    # Get category breakdown
    categories = {}
    for txn in transactions:
        if txn.get("transaction_type") == "debit":
            category = txn.get("category", "UNKNOWN")
            if category in categories:
                categories[category] += txn.get("amount", 0)
            else:
                categories[category] = txn.get("amount", 0)
    
    top_spending_category = max(categories.items(), key=lambda x: x[1])[0] if categories else "Unknown"
    
    # Get investment data
    portfolios_collection = await get_collection("portfolios")
    portfolios = await portfolios_collection.find({
        "user_id": user_id
    }).to_list(length=10)
    
    total_investment = sum(
        portfolio.get("performance", {}).get("current_value", 0) 
        for portfolio in portfolios
    )
    
    # Get asset allocation
    asset_allocation = {}
    for portfolio in portfolios:
        alloc = portfolio.get("asset_allocation", {})
        for asset_class, percentage in alloc.get("current_allocation", {}).items():
            if asset_class in asset_allocation:
                asset_allocation[asset_class] += percentage * portfolio.get("performance", {}).get("current_value", 0) / 100
            else:
                asset_allocation[asset_class] = percentage * portfolio.get("performance", {}).get("current_value", 0) / 100
    
    # Convert to percentages
    if total_investment > 0:
        asset_allocation = {k: round((v / total_investment) * 100, 2) for k, v in asset_allocation.items()}
    
    # Get goals
    goals_collection = await get_collection("goals")
    goals = await goals_collection.find({
        "user_id": user_id,
        "status": {"$ne": "achieved"}
    }).to_list(length=20)
    
    # Calculate goal funding status
    total_goal_target = sum(goal.get("target_amount", 0) for goal in goals)
    total_goal_current = sum(goal.get("current_amount", 0) for goal in goals)
    goals_funding_status = f"{round((total_goal_current / total_goal_target) * 100, 2)}%" if total_goal_target > 0 else "N/A"
    
    # Calculate savings rate
    savings_rate = round(((monthly_income - monthly_expenses) / monthly_income) * 100, 2) if monthly_income > 0 else 0
    
    return {
        "user_id": user_id,
        "income_range": user.get("income_range", "Unknown"),
        "risk_profile": user.get("risk_profile", "Moderate"),
        "accounts": accounts,
        "total_balance": total_balance,
        "monthly_income": monthly_income,
        "monthly_expenses": monthly_expenses,
        "top_spending_category": top_spending_category,
        "savings_rate": savings_rate,
        "total_investment": total_investment,
        "asset_allocation": asset_allocation,
        "goals": goals,
        "goals_funding_status": goals_funding_status
    }

async def _classify_financial_question(question: str) -> str:
    """Classify the financial question topic"""
    try:
        topics = [
            "budgeting", "saving", "investing", "debt", "retirement", 
            "taxes", "insurance", "real_estate", "income", "goals"
        ]
        
        client = get_llm_client()
        response = client.chat.completions.create(
            model="gpt-4" if settings.OPENAI_API_KEY else "gpt-4",
            messages=[
                {
                    "role": "system",
                    "content": f"Classify the following financial question into exactly one of these categories: {', '.join(topics)}. Respond with only the category name."
                },
                {"role": "user", "content": question}
            ],
            max_tokens=20
        )
        
        topic = response.choices[0].message.content.strip().lower()
        return topic if topic in topics else "general"
    
    except Exception as e:
        logger.error(f"Error classifying question: {str(e)}")
        return "general"

async def _get_relevant_financial_data(user_id: str, topic: str) -> Dict[str, Any]:
    """Get relevant financial data based on question topic"""
    # Get basic user data
    users_collection = await get_collection("users")
    user = await users_collection.find_one({"_id": user_id})
    
    if not user:
        raise NotFoundException(detail="User not found")
    
    relevant_data = {
        "income_range": user.get("income_range", "Unknown")
    }
    
    # Get topic-specific data
    if topic == "budgeting" or topic == "saving" or topic == "income":
        # Get recent transactions
        transactions_collection = await get_collection("transactions")
        thirty_days_ago = get_current_time_ist() - timedelta(days=30)
        transactions = await transactions_collection.find({
            "user_id": user_id,
            "date": {"$gte": thirty_days_ago}
        }).to_list(length=500)
        
        # Calculate income and expenses
        income = sum(
            txn.get("amount", 0) 
            for txn in transactions 
            if txn.get("transaction_type") == "credit"
        )
        
        expenses = sum(
            txn.get("amount", 0) 
            for txn in transactions 
            if txn.get("transaction_type") == "debit"
        )
        
        # Get category breakdown
        categories = {}
        for txn in transactions:
            if txn.get("transaction_type") == "debit":
                category = txn.get("category", "UNKNOWN")
                if category in categories:
                    categories[category] += txn.get("amount", 0)
                else:
                    categories[category] = txn.get("amount", 0)
        
        relevant_data.update({
            "monthly_income": income,
            "monthly_expenses": expenses,
            "expense_categories": categories,
            "savings_rate": round(((income - expenses) / income) * 100, 2) if income > 0 else 0
        })
    
    elif topic == "investing":
        # Get investments
        portfolios_collection = await get_collection("portfolios")
        portfolios = await portfolios_collection.find({
            "user_id": user_id
        }).to_list(length=10)
        
        holdings = []
        for portfolio in portfolios:
            for holding in portfolio.get("holdings", []):
                holdings.append({
                    "name": holding.get("instrument_name"),
                    "type": holding.get("instrument_type"),
                    "value": holding.get("current_value"),
                    "gain_loss": holding.get("unrealized_gain_loss_percentage")
                })
        
        relevant_data.update({
            "risk_profile": user.get("risk_profile", "Moderate"),
            "total_investment": sum(portfolio.get("performance", {}).get("current_value", 0) for portfolio in portfolios),
            "holdings": holdings
        })
    
    elif topic == "goals":
        # Get goals
        goals_collection = await get_collection("goals")
        goals = await goals_collection.find({
            "user_id": user_id
        }).to_list(length=20)
        
        goal_data = [{
            "name": goal.get("name"),
            "type": goal.get("goal_type"),
            "target": goal.get("target_amount"),
            "current": goal.get("current_amount"),
            "completion": goal.get("completion_percentage"),
            "target_date": goal.get("target_date"),
            "status": goal.get("status")
        } for goal in goals]
        
        relevant_data.update({
            "goals": goal_data
        })
    
    elif topic == "debt":
        # Get loan accounts
        accounts_collection = await get_collection("accounts")
        loans = await accounts_collection.find({
            "user_id": user_id,
            "account_type": "loan"
        }).to_list(length=20)
        
        credit_cards = await accounts_collection.find({
            "user_id": user_id,
            "account_type": "credit_card"
        }).to_list(length=10)
        
        relevant_data.update({
            "loans": [{
                "name": loan.get("account_name"),
                "balance": loan.get("current_balance"),
                "interest_rate": loan.get("interest_rate")
            } for loan in loans],
            "credit_cards": [{
                "name": cc.get("account_name"),
                "balance": cc.get("current_balance"),
                "limit": cc.get("limit")
            } for cc in credit_cards],
            "total_debt": sum(loan.get("current_balance", 0) for loan in loans) +
                         sum(cc.get("current_balance", 0) for cc in credit_cards)
        })
    
    # Add basic account info to all responses
    accounts_collection = await get_collection("accounts")
    accounts = await accounts_collection.find({
        "user_id": user_id,
        "status": "active"
    }).to_list(length=100)
    
    relevant_data["total_balance"] = sum(account.get("current_balance", 0) for account in accounts)
    
    return relevant_data

async def _get_user_financial_summary(user_id: str) -> Dict[str, Any]:
    """Get summarized financial data for a user"""
    # Simplified version of gathering financial data
    users_collection = await get_collection("users")
    accounts_collection = await get_collection("accounts")
    transactions_collection = await get_collection("transactions")
    
    user = await users_collection.find_one({"_id": user_id})
    accounts = await accounts_collection.find({"user_id": user_id}).to_list(length=100)
    
    thirty_days_ago = get_current_time_ist() - timedelta(days=30)
    recent_transactions = await transactions_collection.find({
        "user_id": user_id,
        "date": {"$gte": thirty_days_ago}
    }).limit(20).to_list(length=20)
    
    # Create summary
    summary = {
        "name": user.get("full_name"),
        "total_balance": sum(account.get("current_balance", 0) for account in accounts),
        "accounts_count": len(accounts),
        "recent_transactions_count": len(recent_transactions),
        "account_types": list(set(account.get("account_type") for account in accounts)),
        "monthly_income": sum(
            txn.get("amount", 0) 
            for txn in recent_transactions 
            if txn.get("transaction_type") == "credit"
        ),
        "monthly_expenses": sum(
            txn.get("amount", 0) 
            for txn in recent_transactions 
            if txn.get("transaction_type") == "debit"
        )
    }
    
    return summary

async def _get_specific_financial_entities(
    user_id: str,
    goal_ids: List[str],
    portfolio_ids: List[str],
    account_ids: List[str]
) -> Dict[str, Any]:
    """Get specific financial entities data by IDs"""
    result = {}
    
    if goal_ids:
        goals_collection = await get_collection("goals")
        goals = await goals_collection.find({
            "_id": {"$in": goal_ids}
        }).to_list(length=len(goal_ids))
        
        result["goals"] = [{
            "id": goal.get("_id"),
            "name": goal.get("name"),
            "target_amount": goal.get("target_amount"),
            "current_amount": goal.get("current_amount"),
            "completion": goal.get("completion_percentage"),
            "target_date": goal.get("target_date").isoformat() if goal.get("target_date") else None
        } for goal in goals]
    
    if portfolio_ids:
        portfolios_collection = await get_collection("portfolios")
        portfolios = await portfolios_collection.find({
            "_id": {"$in": portfolio_ids}
        }).to_list(length=len(portfolio_ids))
        
        result["portfolios"] = [{
            "id": portfolio.get("_id"),
            "name": portfolio.get("name"),
            "current_value": portfolio.get("performance", {}).get("current_value", 0),
            "gain_loss": portfolio.get("performance", {}).get("total_gain_loss_percentage", 0)
        } for portfolio in portfolios]
    
    if account_ids:
        accounts_collection = await get_collection("accounts")
        accounts = await accounts_collection.find({
            "_id": {"$in": account_ids}
        }).to_list(length=len(account_ids))
        
        result["accounts"] = [{
            "id": account.get("_id"),
            "name": account.get("account_name"),
            "type": account.get("account_type"),
            "balance": account.get("current_balance")
        } for account in accounts]
    
    return result

async def _identify_recurring_expenses(user_id: str, categories: Dict[str, Dict]) -> List[Dict[str, Any]]:
    """Identify recurring expenses from transactions"""
    try:
        # Get 3 months of transactions to identify patterns
        transactions_collection = await get_collection("transactions")
        ninety_days_ago = get_current_time_ist() - timedelta(days=90)
        transactions = await transactions_collection.find({
            "user_id": user_id,
            "date": {"$gte": ninety_days_ago},
            "transaction_type": "debit"
        }).to_list(length=1000)
        
        # Group transactions by description and check for monthly pattern
        transaction_groups = {}
        for transaction in transactions:
            description = transaction.get("description", "").lower()
            amount = transaction.get("amount", 0)
            date = transaction.get("date")
            
            key = f"{description}_{amount:.2f}"
            if key in transaction_groups:
                transaction_groups[key]["transactions"].append({
                    "date": date,
                    "amount": amount
                })
            else:
                transaction_groups[key] = {
                    "description": description,
                    "amount": amount,
                    "transactions": [{
                        "date": date,
                        "amount": amount
                    }]
                }
        
        # Identify recurring patterns
        recurring_expenses = []
        for key, group in transaction_groups.items():
            if len(group["transactions"]) >= 2:
                # Sort by date
                group["transactions"].sort(key=lambda x: x["date"])
                
                # Check if transactions occur in different months
                months = set()
                for txn in group["transactions"]:
                    months.add(txn["date"].strftime("%Y-%m"))
                
                if len(months) >= 2:
                    # Likely recurring
                    recurring_expenses.append({
                        "description": group["description"],
                        "amount": group["amount"],
                        "frequency": "monthly" if len(months) >= 3 else "irregular",
                        "occurrences": len(group["transactions"])
                    })
        
        return sorted(recurring_expenses, key=lambda x: x["amount"], reverse=True)[:10]
    
    except Exception as e:
        logger.error(f"Error identifying recurring expenses: {str(e)}")
        return []

async def _identify_unusual_spending(user_id: str, categories: Dict[str, Dict]) -> List[Dict[str, Any]]:
    """Identify unusual spending patterns"""
    try:
        # Get historical category averages from past 6 months
        transactions_collection = await get_collection("transactions")
        six_months_ago = get_current_time_ist() - timedelta(days=180)
        historical_transactions = await transactions_collection.find({
            "user_id": user_id,
            "date": {"$gte": six_months_ago, "$lt": get_current_time_ist() - timedelta(days=30)},
            "transaction_type": "debit"
        }).to_list(length=2000)
        
        # Group by category and month
        historical_categories = {}
        for transaction in historical_transactions:
            category = transaction.get("category", TransactionCategory.UNKNOWN)
            amount = transaction.get("amount", 0)
            month = transaction.get("date").strftime("%Y-%m")
            
            if category not in historical_categories:
                historical_categories[category] = {}
            
            if month in historical_categories[category]:
                historical_categories[category][month] += amount
            else:
                historical_categories[category][month] = amount
        
        # Calculate monthly averages
        category_averages = {}
        for category, months in historical_categories.items():
            if months:
                category_averages[category] = sum(months.values()) / len(months)
        
        # Compare current month to averages
        unusual_spending = []
        for category, data in categories.items():
            if category in category_averages:
                average = category_averages[category]
                current = data["total"]
                
                # If spending is 50% higher than average, mark as unusual
                if current > average * 1.5:
                    unusual_spending.append({
                        "category": category,
                        "current_amount": current,
                        "average_amount": average,
                        "percentage_increase": round(((current - average) / average) * 100, 2),
                        "difference": current - average
                    })
        
        return sorted(unusual_spending, key=lambda x: x["percentage_increase"], reverse=True)
    
    except Exception as e:
        logger.error(f"Error identifying unusual spending: {str(e)}")
        return []

# Import other required modules
import re