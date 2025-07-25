from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, status, Path, Query, BackgroundTasks
from openai import OpenAI
from bson import ObjectId
import logging

from app.config.database import get_collection
from app.config.settings import get_settings
from app.core.security import oauth2_scheme, decode_access_token
from app.core.exceptions import NotFoundException, UnauthorizedException, AIModelException, BadRequestException
from app.schemas.chat import AICoachQuestion, MessageCreate, ChatSessionResponse, MessageResponse, ChatSessionCreate
from app.models.chat import ChatSession, Message, MessageRole, MessageType
from app.utils.helpers import get_current_time_ist, convert_mongo_document



# Get settings
settings = get_settings()

# Configure logger
logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/ai-coach",
    tags=["ai-coach"],
    responses={
        404: {"description": "Not found"},
        401: {"description": "Unauthorized"},
        403: {"description": "Forbidden"},
    },
)

# OpenRouter AI client setup
ai_client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key="currently null it does nto work for ssl problem ",
    #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
)

# Helper function to get current user ID from token
async def get_current_user_id(token: str = Depends(oauth2_scheme)) -> str:
    """Get current user ID from token"""
    payload = decode_access_token(token)
    user_id = payload.get("sub")
    if not user_id:
        raise UnauthorizedException(detail="Invalid token")
    return user_id

@router.post("/chat", response_model=Dict[str, Any])
async def chat_with_ai(
    chat_data: AICoachQuestion,
    token: str = Depends(oauth2_scheme)
):
    """
    Chat with the AI financial coach
    
    This endpoint allows users to ask questions about their finances and get personalized advice
    """
    logger.info("Processing AI coach chat request")
    
    user_id = await get_current_user_id(token)
    
    # Verify user ID matches the requested user_id for security
    if user_id != chat_data.user_id:
        logger.error(f"User ID mismatch: {user_id} vs {chat_data.user_id}")
        raise UnauthorizedException(detail="User ID does not match authentication")
    
    try:
        # Get user context from database
        users_collection = await get_collection("users")
        user = await users_collection.find_one({"_id": ObjectId(user_id)})
        
        if not user:
            raise NotFoundException(detail="User not found")
        
        # Get financial context for the user
        financial_context = await _gather_user_financial_data(user_id)
        
        # Handle session management
        session_id = chat_data.session_id
        
        if not session_id:
            # Create a new session
            sessions_collection = await get_collection("chat_sessions")
            
            new_session = ChatSession(
                user_id=user_id,
                title="Financial Conversation",
                session_type="financial_advice",
                context={
                    "risk_profile": user.get("risk_profile", "moderate"),
                    "financial_summary": financial_context
                }
            )
            
            result = await sessions_collection.insert_one(new_session.dict())
            session_id = str(result.inserted_id)
            
            # Add initial system message
            await _add_system_message(session_id)
        else:
            # Verify session exists and belongs to user
            sessions_collection = await get_collection("chat_sessions")
            session = await sessions_collection.find_one({
                "_id": ObjectId(session_id),
                "user_id": user_id
            })
            
            if not session:
                raise NotFoundException(detail="Chat session not found")
        
        # Save user message
        messages_collection = await get_collection("messages")
        user_message = Message(
            session_id=session_id,
            role=MessageRole.USER,
            content=chat_data.question,
            message_type=MessageType.TEXT
        )
        
        await messages_collection.insert_one(user_message.dict())
        
        # Get conversation history
        message_history = await _get_session_messages(session_id)
        
        # Format messages for the AI service
        formatted_messages = []
        
        # Add a system message with user context
        formatted_messages.append({
            "role": "system",
            "content": f"""You are a financial advisor assistant for an AI-powered personal finance platform.
                Your name is FinCoach. You are helping a user with their finances. Here is some context about the user:
                - Name: {user.get('full_name', 'User')}
                - Risk profile: {user.get('risk_profile', 'moderate')}
                - Income range: {user.get('income_range', 'Not specified')}
                
                Financial Summary:
                - Total balance: {financial_context.get('total_balance', 'Not available')}
                - Monthly income: {financial_context.get('monthly_income', 'Not available')}
                - Monthly expenses: {financial_context.get('monthly_expenses', 'Not available')}
                - Top spending category: {financial_context.get('top_spending_category', 'Not available')}
                
                Provide personalized financial advice based on this information.
                Keep responses focused, practical, and specific to Indian financial context.
                Suggest specific actions the user can take to improve their finances.
                """
        })
        
        # Add conversation history
        for msg in message_history[-10:]:  # Limit to 10 most recent messages
            role = "user" if msg["role"] == MessageRole.USER else "assistant"
            formatted_messages.append({
                "role": role,
                "content": msg["content"]
            })
        
        # Call OpenRouter AI API
        try:
            completion = ai_client.chat.completions.create(
                extra_headers={
                    "HTTP-Referer": settings.APP_FRONTEND_URL,
                    "X-Title": "Fintech AI Platform",
                },
                model="deepseek/deepseek-r1-0528-qwen3-8b:free",
                messages=formatted_messages
            )
            
            ai_response = completion.choices[0].message.content
            
            # Save AI response to database
            ai_message = Message(
                session_id=session_id,
                role=MessageRole.ASSISTANT,
                content=ai_response,
                message_type=MessageType.TEXT,
                ai_model="deepseek/deepseek-r1-0528-qwen3-8b:free",
                tokens_used=completion.usage.total_tokens if hasattr(completion, 'usage') else None
            )
            
            await messages_collection.insert_one(ai_message.dict())
            
            # Update session metadata
            await sessions_collection.update_one(
                {"_id": ObjectId(session_id)},
                {
                    "$set": {
                        "last_message_at": get_current_time_ist(),
                        "updated_at": get_current_time_ist()
                    },
                    "$inc": {"interaction_count": 1}
                }
            )
            
            return {
                "session_id": session_id,
                "user_message": chat_data.question,
                "ai_response": ai_response,
                "created_at": get_current_time_ist()
            }
            
        except Exception as e:
            logger.error(f"Error calling AI service: {str(e)}")
            raise AIModelException(detail=f"Failed to generate response: {str(e)}")
    
    except Exception as e:
        if isinstance(e, (NotFoundException, UnauthorizedException, AIModelException)):
            raise
        logger.error(f"Error in chat_with_ai: {str(e)}")
        raise AIModelException(detail=f"AI chat processing failed: {str(e)}")

@router.get("/insights", response_model=Dict[str, Any])
async def get_financial_insights(
    token: str = Depends(oauth2_scheme),
    timeframe: str = Query("month", description="Timeframe for insights (week, month, quarter, year)")
):
    """
    Get AI-generated insights about the user's financial situation
    
    This endpoint analyzes transactions, goals, and portfolios to provide personalized insights
    
    - **timeframe**: Time period for analysis (week, month, quarter, year)
    """
    logger.info("Generating financial insights")
    
    user_id = await get_current_user_id(token)
    
    try:
        # Get financial context
        financial_context = await _gather_user_financial_data(user_id, timeframe)
        
        # Define base time period
        now = get_current_time_ist()
        if timeframe == "week":
            start_date = now - timedelta(days=7)
            period_name = "Weekly"
        elif timeframe == "month":
            start_date = now - timedelta(days=30)
            period_name = "Monthly"
        elif timeframe == "quarter":
            start_date = now - timedelta(days=90)
            period_name = "Quarterly"
        elif timeframe == "year":
            start_date = now - timedelta(days=365)
            period_name = "Annual"
        else:
            start_date = now - timedelta(days=30)
            period_name = "Monthly"
        
        # Get transactions for the timeframe
        transactions_collection = await get_collection("transactions")
        transactions = await transactions_collection.find({
            "user_id": user_id,
            "date": {"$gte": start_date}
        }).to_list(length=1000)
        
        # Calculate key metrics
        income = sum(t["amount"] for t in transactions if t["transaction_type"] == "credit")
        expenses = sum(t["amount"] for t in transactions if t["transaction_type"] == "debit")
        
        # Group expenses by category
        category_expenses = {}
        for txn in transactions:
            if txn["transaction_type"] == "debit":
                category = txn.get("category", "other")
                if category not in category_expenses:
                    category_expenses[category] = 0
                category_expenses[category] += txn["amount"]
        
        # Get top spending categories
        top_categories = sorted(category_expenses.items(), key=lambda x: x[1], reverse=True)[:5]
        
        # Calculate savings rate
        savings_rate = ((income - expenses) / income * 100) if income > 0 else 0
        
        # Analyze recurring expenses
        recurring_expenses = await _identify_recurring_expenses(user_id, transactions)
        total_recurring = sum(item["amount"] for item in recurring_expenses)
        recurring_percentage = (total_recurring / expenses * 100) if expenses > 0 else 0
        
        # Identify unusual spending
        unusual_spending = await _identify_unusual_spending(user_id, transactions)
        
        # Get investment data
        portfolios_collection = await get_collection("portfolios")
        portfolios = await portfolios_collection.find({
            "user_id": user_id,
            "is_active": True
        }).to_list(length=10)
        
        total_invested = sum(p.get("performance", {}).get("current_value", 0) for p in portfolios)
        investment_growth = sum(p.get("performance", {}).get("total_gain_loss", 0) for p in portfolios)
        
        # Generate insights prompt for AI
        insights_prompt = f"""
        Generate 5 personalized financial insights based on the following data:
        
        Financial Summary:
        - {period_name} Income: ₹{income}
        - {period_name} Expenses: ₹{expenses}
        - Savings Rate: {savings_rate:.1f}%
        - Top Expense Category: {top_categories[0][0] if top_categories else "None"}
        - Recurring Expenses: {recurring_percentage:.1f}% of total spending
        - Total Investments: ₹{total_invested}
        - Investment Growth: ₹{investment_growth}
        
        Unusual Spending:
        {", ".join([f"{item['category']} (₹{item['amount']})" for item in unusual_spending[:3]])}
        
        Provide specific, actionable insights focused on:
        1. Spending patterns
        2. Savings opportunities
        3. Budget improvements
        4. Investment suggestions
        5. Financial goals
        
        Format each insight with a title and description.
        """
        
        # Call OpenRouter AI API for insights
        try:
            completion = ai_client.chat.completions.create(
                extra_headers={
                    "HTTP-Referer": settings.APP_FRONTEND_URL,
                    "X-Title": "Fintech AI Platform",
                },
                model="deepseek/deepseek-r1-0528-qwen3-8b:free",
                messages=[
                    {"role": "system", "content": "You are a financial insights generator. Generate concise, specific financial insights based on the provided data."},
                    {"role": "user", "content": insights_prompt}
                ]
            )
            
            ai_insights = completion.choices[0].message.content
            
            # Process insights text into structured format
            insights_list = _process_insights_text(ai_insights)
            
            # Save insights to database
            insights_collection = await get_collection("financial_insights")
            insight_record = {
                "user_id": user_id,
                "timeframe": timeframe,
                "insights": insights_list,
                "financial_context": {
                    "income": income,
                    "expenses": expenses,
                    "savings_rate": savings_rate,
                    "top_categories": top_categories,
                    "recurring_expenses": recurring_percentage,
                    "total_invested": total_invested
                },
                "created_at": get_current_time_ist()
            }
            
            await insights_collection.insert_one(insight_record)
            
            return {
                "timeframe": timeframe,
                "insights": insights_list,
                "summary": {
                    "income": income,
                    "expenses": expenses,
                    "savings_rate": savings_rate,
                    "top_expense_categories": dict(top_categories),
                    "recurring_expenses": {
                        "total": total_recurring,
                        "percentage": recurring_percentage,
                        "items": recurring_expenses[:5]  # Limit to top 5
                    }
                }
            }
            
        except Exception as e:
            logger.error(f"Error generating insights: {str(e)}")
            raise AIModelException(detail=f"Failed to generate insights: {str(e)}")
    
    except Exception as e:
        if isinstance(e, (NotFoundException, UnauthorizedException, AIModelException)):
            raise
        logger.error(f"Error in get_financial_insights: {str(e)}")
        raise AIModelException(detail=f"AI insights processing failed: {str(e)}")

@router.post("/analyze-spending", response_model=Dict[str, Any])
async def analyze_spending(
    token: str = Depends(oauth2_scheme),
    start_date: Optional[datetime] = Query(None, description="Start date for analysis"),
    end_date: Optional[datetime] = Query(None, description="End date for analysis"),
    category: Optional[str] = Query(None, description="Filter by specific category")
):
    """
    Analyze spending patterns and provide insights
    
    This endpoint provides detailed analysis of spending patterns with AI-powered suggestions
    
    - **start_date**: Start date for analysis (defaults to 30 days ago)
    - **end_date**: End date for analysis (defaults to today)
    - **category**: Optional filter by transaction category
    """
    logger.info("Analyzing spending patterns")
    
    user_id = await get_current_user_id(token)
    
    try:
        # Set default date range if not specified
        now = get_current_time_ist()
        if not end_date:
            end_date = now
        
        if not start_date:
            start_date = now - timedelta(days=30)
        
        # Build query for transactions
        query = {
            "user_id": user_id,
            "date": {"$gte": start_date, "$lte": end_date},
            "transaction_type": "debit"  # Only analyze expenses
        }
        
        if category:
            query["category"] = category
        
        # Get transactions
        transactions_collection = await get_collection("transactions")
        transactions = await transactions_collection.find(query).to_list(length=1000)
        
        if not transactions:
            return {
                "message": "No transaction data found for the specified period",
                "analysis": {},
                "recommendations": []
            }
        
        # Group transactions by category
        categories = {}
        for txn in transactions:
            category = txn.get("category", "other")
            if category not in categories:
                categories[category] = {
                    "total": 0,
                    "count": 0,
                    "transactions": []
                }
            categories[category]["total"] += txn["amount"]
            categories[category]["count"] += 1
            categories[category]["transactions"].append({
                "id": str(txn.get("_id")),
                "amount": txn["amount"],
                "date": txn["date"],
                "description": txn["description"],
                "merchant": txn.get("merchant", {}).get("name") if txn.get("merchant") else None
            })
        
        # Calculate total spending
        total_spending = sum(cat["total"] for cat in categories.values())
        
        # Calculate percentages
        for cat_name, cat_data in categories.items():
            cat_data["percentage"] = (cat_data["total"] / total_spending * 100) if total_spending > 0 else 0
        
        # Sort categories by total amount
        sorted_categories = sorted(categories.items(), key=lambda x: x[1]["total"], reverse=True)
        
        # Analyze spending trends over time
        # Group by week
        weekly_spending = {}
        for txn in transactions:
            week_start = txn["date"].replace(hour=0, minute=0, second=0, microsecond=0)
            week_start = week_start - timedelta(days=week_start.weekday())
            week_key = week_start.strftime("%Y-%m-%d")
            
            if week_key not in weekly_spending:
                weekly_spending[week_key] = 0
            weekly_spending[week_key] += txn["amount"]
        
        # Merchant analysis
        merchants = {}
        for txn in transactions:
            merchant = txn.get("merchant", {}).get("name") if txn.get("merchant") else txn["description"]
            if merchant not in merchants:
                merchants[merchant] = 0
            merchants[merchant] += txn["amount"]
        
        top_merchants = sorted(merchants.items(), key=lambda x: x[1], reverse=True)[:10]
        
        # Generate spending analysis prompt for AI
        analysis_prompt = f"""
        Generate a spending analysis and 3-5 personalized recommendations based on the following data:
        
        Time Period: {start_date.strftime('%d %b %Y')} to {end_date.strftime('%d %b %Y')}
        Total Spending: ₹{total_spending}
        
        Top Spending Categories:
        {', '.join([f"{cat}: ₹{data['total']} ({data['percentage']:.1f}%)" for cat, data in sorted_categories[:5]])}
        
        Top Merchants:
        {', '.join([f"{merchant}: ₹{amount}" for merchant, amount in top_merchants[:5]])}
        
        Weekly Spending Pattern:
        {', '.join([f"{week}: ₹{amount}" for week, amount in weekly_spending.items()])}
        
        Please analyze the spending patterns and provide:
        1. Key observations about spending habits
        2. 3-5 specific, actionable recommendations to optimize spending
        3. Note any concerning patterns or opportunities for savings
        
        Format the analysis as plain text paragraphs and the recommendations as a numbered list.
        """
        
        # Call OpenRouter AI API for analysis
        try:
            completion = ai_client.chat.completions.create(
                extra_headers={
                    "HTTP-Referer": settings.APP_FRONTEND_URL,
                    "X-Title": "Fintech AI Platform",
                },
                model="deepseek/deepseek-r1-0528-qwen3-8b:free",
                messages=[
                    {"role": "system", "content": "You are a financial analysis assistant. Analyze spending patterns and provide actionable recommendations."},
                    {"role": "user", "content": analysis_prompt}
                ]
            )
            
            ai_analysis = completion.choices[0].message.content
            
            # Extract recommendations
            recommendations = _extract_recommendations(ai_analysis)
            
            # Save analysis to database
            analysis_collection = await get_collection("spending_analysis")
            analysis_record = {
                "user_id": user_id,
                "start_date": start_date,
                "end_date": end_date,
                "category_filter": category,
                "total_spending": total_spending,
                "categories": {k: v for k, v in categories.items()},
                "weekly_spending": weekly_spending,
                "top_merchants": dict(top_merchants),
                "ai_analysis": ai_analysis,
                "recommendations": recommendations,
                "created_at": get_current_time_ist()
            }
            
            await analysis_collection.insert_one(analysis_record)
            
            return {
                "period": {
                    "start_date": start_date,
                    "end_date": end_date
                },
                "total_spending": total_spending,
                "categories": {k: {
                    "total": v["total"],
                    "count": v["count"],
                    "percentage": v["percentage"]
                } for k, v in categories.items()},
                "weekly_trend": weekly_spending,
                "top_merchants": dict(top_merchants),
                "analysis": ai_analysis,
                "recommendations": recommendations
            }
            
        except Exception as e:
            logger.error(f"Error analyzing spending: {str(e)}")
            raise AIModelException(detail=f"Failed to analyze spending: {str(e)}")
    
    except Exception as e:
        if isinstance(e, (NotFoundException, UnauthorizedException, AIModelException)):
            raise
        logger.error(f"Error in analyze_spending: {str(e)}")
        raise AIModelException(detail=f"Spending analysis failed: {str(e)}")

# Helper functions
async def _gather_user_financial_data(user_id: str, timeframe: str = "month") -> Dict[str, Any]:
    """Gather user's financial data for AI processing"""
    # Get user profile
    users_collection = await get_collection("users")
    user = await users_collection.find_one({"_id": ObjectId(user_id)})
    
    if not user:
        raise NotFoundException(detail="User not found")
    
    # Get accounts
    accounts_collection = await get_collection("accounts")
    accounts = await accounts_collection.find(
        {"user_id": user_id, "status": "active"}
    ).to_list(length=100)
    
    total_balance = sum(account.get("current_balance", 0) for account in accounts)
    
    # Get transactions based on timeframe
    now = get_current_time_ist()
    if timeframe == "week":
        period_start = now - timedelta(days=7)
    elif timeframe == "month":
        period_start = now - timedelta(days=30)
    elif timeframe == "quarter":
        period_start = now - timedelta(days=90)
    elif timeframe == "year":
        period_start = now - timedelta(days=365)
    else:
        period_start = now - timedelta(days=30)
    
    transactions_collection = await get_collection("transactions")
    transactions = await transactions_collection.find({
        "user_id": user_id,
        "date": {"$gte": period_start}
    }).to_list(length=1000)
    
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
            category = txn.get("category", "other")
            if category not in categories:
                categories[category] = 0
            categories[category] += txn.get("amount", 0)
    
    top_spending_category = max(categories.items(), key=lambda x: x[1])[0] if categories else "Unknown"
    
    # Get goals
    goals_collection = await get_collection("goals")
    goals = await goals_collection.find({"user_id": user_id}).to_list(length=20)
    
    # Get portfolios
    portfolios_collection = await get_collection("portfolios")
    portfolios = await portfolios_collection.find({"user_id": user_id}).to_list(length=10)
    
    return {
        "total_balance": total_balance,
        "monthly_income": monthly_income,
        "monthly_expenses": monthly_expenses,
        "top_spending_category": top_spending_category,
        "spending_by_category": categories,
        "account_count": len(accounts),
        "goal_count": len(goals),
        "portfolio_count": len(portfolios),
        "timeframe": timeframe
    }

async def _get_session_messages(session_id: str) -> List[Dict[str, Any]]:
    """Get messages for a chat session"""
    messages_collection = await get_collection("messages")
    messages = await messages_collection.find({"session_id": session_id}).sort("created_at", 1).to_list(length=100)
    return [convert_mongo_document(msg) for msg in messages]

async def _add_system_message(session_id: str) -> Dict[str, Any]:
    """Add initial system message to a chat session"""
    system_prompt = """
    You are FinCoach, a financial advisor assistant for the Fintech AI Platform.
    
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
    
    result = await messages_collection.insert_one(system_message.dict())
    return system_message.dict()

async def _identify_recurring_expenses(user_id: str, transactions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Identify recurring expenses from transactions"""
    # Group transactions by description/merchant
    merchants = {}
    for txn in transactions:
        if txn.get("transaction_type") != "debit":
            continue
            
        merchant = txn.get("merchant", {}).get("name") if txn.get("merchant") else txn.get("description", "")
        if merchant not in merchants:
            merchants[merchant] = []
            
        merchants[merchant].append({
            "amount": txn.get("amount", 0),
            "date": txn.get("date")
        })
    
    # Identify recurring patterns
    recurring = []
    for merchant, txns in merchants.items():
        if len(txns) >= 2:  # At least 2 transactions
            # Calculate average interval between transactions
            dates = sorted([t["date"] for t in txns])
            if len(dates) >= 2:
                intervals = [(dates[i+1] - dates[i]).days for i in range(len(dates)-1)]
                avg_interval = sum(intervals) / len(intervals)
                std_dev = (sum((i - avg_interval) ** 2 for i in intervals) / len(intervals)) ** 0.5
                
                # If consistent interval (std_dev < 5 days) and avg_interval < 35 days
                if std_dev < 5 and avg_interval < 35:
                    avg_amount = sum(t["amount"] for t in txns) / len(txns)
                    recurring.append({
                        "merchant": merchant,
                        "frequency": "monthly" if 25 <= avg_interval <= 35 else "weekly" if 6 <= avg_interval <= 8 else "bi-weekly" if 13 <= avg_interval <= 15 else "unknown",
                        "amount": avg_amount,
                        "transactions": len(txns)
                    })
    
    return sorted(recurring, key=lambda x: x["amount"], reverse=True)

async def _identify_unusual_spending(user_id: str, transactions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Identify unusual spending patterns"""
    # Group transactions by category and date
    categories = {}
    for txn in transactions:
        if txn.get("transaction_type") != "debit":
            continue
            
        category = txn.get("category", "other")
        date = txn.get("date").strftime("%Y-%m-%d")
        
        if category not in categories:
            categories[category] = {}
            
        if date not in categories[category]:
            categories[category][date] = 0
            
        categories[category][date] += txn.get("amount", 0)
    
    # Calculate average daily spend by category
    category_averages = {}
    for category, dates in categories.items():
        values = list(dates.values())
        if values:
            avg = sum(values) / len(values)
            std_dev = (sum((v - avg) ** 2 for v in values) / len(values)) ** 0.5
            category_averages[category] = {"avg": avg, "std_dev": std_dev}
    
    # Find unusually high spending days (> 2 std devs)
    unusual = []
    for category, dates in categories.items():
        avg = category_averages[category]["avg"]
        std_dev = category_averages[category]["std_dev"]
        threshold = avg + (2 * std_dev)
        
        for date, amount in dates.items():
            if amount > threshold and amount > 1000:  # Minimum threshold of ₹1000
                unusual.append({
                    "category": category,
                    "date": date,
                    "amount": amount,
                    "average": avg,
                    "percent_above_average": ((amount - avg) / avg * 100) if avg > 0 else 100
                })
    
    return sorted(unusual, key=lambda x: x["percent_above_average"], reverse=True)

def _process_insights_text(text: str) -> List[Dict[str, str]]:
    """Process raw AI output into structured insights"""
    lines = text.strip().split('\n')
    insights = []
    current_insight = None
    current_description = []
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # Check if line starts with a number or has a specific format of insight headings
        if line[0].isdigit() and '. ' in line[:5]:
            # Save previous insight if exists
            if current_insight:
                insights.append({
                    "title": current_insight,
                    "description": '\n'.join(current_description)
                })
            
            # Start new insight
            parts = line.split('. ', 1)
            if len(parts) > 1:
                current_insight = parts[1].strip()
                current_description = []
            else:
                current_insight = line.strip()
                current_description = []
        elif ":" in line and len(line.split(":", 1)[0]) < 50:
            # Title with colon format like "Insight Title: Description"
            parts = line.split(":", 1)
            # Save previous insight if exists
            if current_insight:
                insights.append({
                    "title": current_insight,
                    "description": '\n'.join(current_description)
                })
            current_insight = parts[0].strip()
            current_description = [parts[1].strip()] if len(parts) > 1 else []
        else:
            # Add to current description
            if current_insight:
                current_description.append(line)
    
    # Add the last insight
    if current_insight:
        insights.append({
            "title": current_insight,
            "description": '\n'.join(current_description)
        })
    
    return insights

def _extract_recommendations(text: str) -> List[str]:
    """Extract recommendations from AI analysis output"""
    recommendations = []
    in_recommendations = False
    
    lines = text.strip().split('\n')
    for line in lines:
        line = line.strip()
        
        # Check if we're entering the recommendations section
        if 'recommendations' in line.lower() and ':' in line:
            in_recommendations = True
            continue
            
        # If we're in recommendations and line starts with a number, it's a recommendation
        if in_recommendations:
            if len(line) > 2 and line[0].isdigit() and line[1] in ['.', ')']:
                recommendations.append(line[2:].strip())
            elif line.startswith('- '):
                recommendations.append(line[2:].strip())
    
    # If no clear recommendations section was found, look for numbered items anywhere
    if not recommendations:
        for line in lines:
            line = line.strip()
            if len(line) > 2 and line[0].isdigit() and line[1] in ['.', ')']:
                recommendations.append(line[2:].strip())
    
    return recommendations