from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
import uuid
from fastapi import APIRouter, Depends, HTTPException, status, Path, Query
from bson import ObjectId

from app.config.database import get_collection
from app.core.security import oauth2_scheme, decode_access_token
from app.core.exceptions import NotFoundException, UnauthorizedException, ExternalAPIException, BadRequestException
from app.schemas.transaction import (
    TransactionResponse, 
    TransactionSummaryResponse,
    TransactionCreate,
    TransactionUpdate,
    TransactionFilters,
    CategorySummary,
    TransactionAnalytics,
    SplitTransactionRequest
)
from app.models.transaction import Transaction, TransactionCategory, TransactionType, TransactionStatus
from app.utils.helpers import get_current_time_ist, convert_mongo_document

# Import AI service for insights (you would need to implement this)
# from app.services.ai_service import generate_transaction_insights

router = APIRouter(
    prefix="/transactions",
    tags=["transactions"],
    responses={
        404: {"description": "Not found"},
        401: {"description": "Unauthorized"},
        403: {"description": "Forbidden"},
    },
)

# Helper function to get current user ID from token
async def get_current_user_id(token: str = Depends(oauth2_scheme)) -> str:
    """Get current user ID from token"""
    payload = decode_access_token(token)
    user_id = payload.get("sub")
    if not user_id:
        raise UnauthorizedException(detail="Invalid token")
    return user_id

@router.get("", response_model=List[TransactionSummaryResponse])
async def list_transactions(
    token: str = Depends(oauth2_scheme),
    account_id: Optional[str] = Query(None, description="Filter by account ID"),
    start_date: Optional[datetime] = Query(None, description="Filter by start date"),
    end_date: Optional[datetime] = Query(None, description="Filter by end date"),
    category: Optional[str] = Query(None, description="Filter by transaction category"),
    min_amount: Optional[float] = Query(None, description="Filter by minimum amount"),
    max_amount: Optional[float] = Query(None, description="Filter by maximum amount"),
    transaction_type: Optional[str] = Query(None, description="Filter by transaction type (debit, credit)"),
    search: Optional[str] = Query(None, description="Search in description"),
    include_split: Optional[bool] = Query(True, description="Include original split transactions"),
    skip: int = Query(0, description="Number of records to skip for pagination"),
    limit: int = Query(50, description="Maximum number of records to return")
):
    """
    List transactions for the current user with optional filters
    """
    import logging
    logger = logging.getLogger(__name__)

    user_id = await get_current_user_id(token)

    # Build filter
    filter_query = {"user_id": user_id}

    # Filter by split transactions if requested
    if not include_split:
        filter_query["$or"] = [
            {"is_split": {"$exists": False}},
            {"is_split": False}
        ]

    if account_id:
        filter_query["account_id"] = account_id

    if start_date:
        filter_query.setdefault("date", {})
        filter_query["date"]["$gte"] = start_date

    if end_date:
        filter_query.setdefault("date", {})
        filter_query["date"]["$lte"] = end_date

    # Only add category filter if provided and not None
    if category is not None:
        # Try to match both Enum and string
        filter_query["category"] = {
            "$in": [
                category,
                category.lower(),
                category.upper(),
                getattr(TransactionCategory, category.upper(), category)
            ]
        }

    # Only add transaction_type filter if provided and not None
    if transaction_type is not None:
        filter_query["transaction_type"] = {
            "$in": [
                transaction_type,
                transaction_type.lower(),
                transaction_type.upper(),
                getattr(TransactionType, transaction_type.upper(), transaction_type)
            ]
        }

    if min_amount is not None:
        filter_query.setdefault("amount", {})
        filter_query["amount"]["$gte"] = min_amount

    if max_amount is not None:
        filter_query.setdefault("amount", {})
        filter_query["amount"]["$lte"] = max_amount

    if search:
        search_filter = {
            "$or": [
                {"description": {"$regex": search, "$options": "i"}},
                {"original_description": {"$regex": search, "$options": "i"}}
            ]
        }
        if "$or" in filter_query:
            filter_query = {
                "$and": [
                    {"$or": filter_query.pop("$or")},
                    search_filter
                ],
                **filter_query
            }
        else:
            filter_query.update(search_filter)

    logger.debug(f"Transaction filter query: {filter_query}")

    transactions_collection = await get_collection("transactions")
    transactions = await transactions_collection.find(filter_query).sort("date", -1).skip(skip).limit(limit).to_list(length=limit)

    result = []
    for transaction in transactions:
        transaction_data = convert_mongo_document(transaction)
        merchant_name = None
        if "merchant" in transaction_data and transaction_data["merchant"]:
            merchant_name = transaction_data["merchant"].get("name")

        # Use .get() for all fields, provide fallback values
        result.append(TransactionSummaryResponse(
            id=transaction_data.get("id", str(transaction_data.get("_id", ""))),
            transaction_id=transaction_data.get("transaction_id", transaction_data.get("id", "")),
            account_id=transaction_data.get("account_id", ""),
            amount=transaction_data.get("amount", 0.0),
            transaction_type=transaction_data.get("transaction_type", TransactionType.OTHER),
            description=transaction_data.get("description", ""),
            date=transaction_data.get("date", datetime.now()),
            category=transaction_data.get("category", TransactionCategory.UNKNOWN),
            merchant_name=merchant_name,
            status=transaction_data.get("status", TransactionStatus.COMPLETED)
        ))

    return result

@router.get("/categories", response_model=List[CategorySummary])
async def get_transaction_categories(
    token: str = Depends(oauth2_scheme),
    start_date: Optional[datetime] = Query(None, description="Filter by start date"),
    end_date: Optional[datetime] = Query(None, description="Filter by end date"),
    account_id: Optional[str] = Query(None, description="Filter by account ID"),
    transaction_type: Optional[TransactionType] = Query(None, description="Filter by transaction type")
):
    """
    Get spending or income by category
    """
    import logging
    logger = logging.getLogger(__name__)
    logger.info("Processing transaction categories request")
    
    user_id = await get_current_user_id(token)
    
    # Build filter
    filter_query = {"user_id": user_id}
    
    if account_id:
        try:
            object_account_id = ObjectId(account_id)
            filter_query["account_id"] = account_id
        except Exception:
            filter_query["account_id"] = account_id
    
    if start_date:
        filter_query["date"] = {"$gte": start_date}
    
    if end_date:
        if "date" in filter_query:
            filter_query["date"]["$lte"] = end_date
        else:
            filter_query["date"] = {"$lte": end_date}
    
    if transaction_type:
        filter_query["transaction_type"] = transaction_type
    
    logger.debug(f"Category filter query: {filter_query}")
    
    try:
        # Get transactions from database
        transactions_collection = await get_collection("transactions")
        
        # Use MongoDB aggregation for category summary
        pipeline = [
            {"$match": filter_query},
            {"$group": {
                "_id": "$category",
                "total_amount": {"$sum": "$amount"},
                "transaction_count": {"$sum": 1}
            }},
            {"$sort": {"total_amount": -1}}
        ]
        
        logger.debug(f"Aggregation pipeline: {pipeline}")
        category_data = await transactions_collection.aggregate(pipeline).to_list(length=100)
        
        # Calculate total for percentage
        total_amount = sum(item["total_amount"] for item in category_data) if category_data else 0
        
        # Convert to response model
        result = []
        for item in category_data:
            percentage = (item["total_amount"] / total_amount * 100) if total_amount > 0 else 0
            result.append(CategorySummary(
                category=item["_id"],
                total_amount=item["total_amount"],
                transaction_count=item["transaction_count"],
                percentage=percentage
            ))
        
        logger.info(f"Found {len(result)} transaction categories")
        return result
    except Exception as e:
        logger.error(f"Error getting transaction categories: {str(e)}", exc_info=True)
        raise BadRequestException(detail=f"Error getting transaction categories: {str(e)}")

@router.get("/insights", status_code=status.HTTP_200_OK)
async def get_transaction_insights(
    token: str = Depends(oauth2_scheme),
    start_date: Optional[datetime] = Query(None, description="Filter by start date"),
    end_date: Optional[datetime] = Query(None, description="Filter by end date"),
    account_id: Optional[str] = Query(None, description="Filter by account ID")
):
    """
    Get AI-generated insights about transactions
    """
    user_id = await get_current_user_id(token)
    
    # Set default date range to last 30 days if not specified
    if not end_date:
        end_date = get_current_time_ist()
    
    if not start_date:
        start_date = end_date - timedelta(days=30)
    
    # Build filter
    filter_query = {"user_id": user_id}
    
    if account_id:
        try:
            object_account_id = ObjectId(account_id)
            filter_query["account_id"] = account_id
        except Exception:
            filter_query["account_id"] = account_id
    
    filter_query["date"] = {"$gte": start_date, "$lte": end_date}
    
    # Get transactions from database
    transactions_collection = await get_collection("transactions")
    transactions = await transactions_collection.find(filter_query).to_list(length=1000)
    
    # Calculate basic analytics
    income_transactions = [t for t in transactions if t["transaction_type"] == TransactionType.CREDIT]
    expense_transactions = [t for t in transactions if t["transaction_type"] == TransactionType.DEBIT]
    
    total_income = sum(t["amount"] for t in income_transactions)
    total_expenses = sum(t["amount"] for t in expense_transactions)
    
    # Calculate top spending categories
    category_spending = {}
    for t in expense_transactions:
        category = t.get("category", TransactionCategory.UNKNOWN)
        if category in category_spending:
            category_spending[category] += t["amount"]
        else:
            category_spending[category] = t["amount"]
    
    top_spending = []
    for category, amount in sorted(category_spending.items(), key=lambda x: x[1], reverse=True)[:5]:
        percentage = (amount / total_expenses * 100) if total_expenses > 0 else 0
        top_spending.append({
            "category": category,
            "amount": amount,
            "percentage": percentage
        })
    
    # Calculate period comparison (compare with previous period)
    prev_start = start_date - (end_date - start_date)
    prev_end = start_date
    
    prev_filter_query = filter_query.copy()
    prev_filter_query["date"] = {"$gte": prev_start, "$lte": prev_end}
    
    prev_transactions = await transactions_collection.find(prev_filter_query).to_list(length=1000)
    prev_expenses = sum(t["amount"] for t in prev_transactions if t["transaction_type"] == TransactionType.DEBIT)
    
    period_comparison = {
        "current_period_expenses": total_expenses,
        "previous_period_expenses": prev_expenses,
        "change_percentage": ((total_expenses - prev_expenses) / prev_expenses * 100) if prev_expenses > 0 else 0
    }
    
    # For now, return basic insights
    # In a production app, you would call the AI service for deeper insights
    insights = {
        "summary": f"You earned {total_income:.2f} and spent {total_expenses:.2f} during this period.",
        "top_spending_categories": top_spending,
        "period_comparison": period_comparison,
        "recommendations": [
            "Based on your spending patterns, you might want to consider reducing expenses in your top category.",
            "Your income to expense ratio looks healthy." if total_income > total_expenses else "Consider budgeting to reduce expenses."
        ]
    }
    
    return insights

@router.get("/{transaction_id}", response_model=TransactionResponse)
async def get_transaction(
    transaction_id: str = Path(..., description="Transaction ID"),
    token: str = Depends(oauth2_scheme)
):
    """
    Get details of a specific transaction by ID
    """
    user_id = await get_current_user_id(token)
    
    # Get transaction from database
    transactions_collection = await get_collection("transactions")
    
    # Try both string ID and MongoDB ObjectId
    transaction = None
    
    # First try with string ID
    transaction = await transactions_collection.find_one({
        "user_id": user_id,
        "$or": [
            {"id": transaction_id},
            {"transaction_id": transaction_id}
        ]
    })
    
    # If not found, try with ObjectId
    if not transaction:
        try:
            object_id = ObjectId(transaction_id)
            transaction = await transactions_collection.find_one({
                "_id": object_id,
                "user_id": user_id
            })
        except Exception:
            pass
    
    if not transaction:
        raise NotFoundException(detail="Transaction not found")
    
    # --- Ensure required fields are present ---
    if "transaction_id" not in transaction:
        transaction["transaction_id"] = str(transaction.get("id", transaction.get("_id", "")))
    if "original_description" not in transaction:
        transaction["original_description"] = transaction.get("description", "")
    # ------------------------------------------

    return convert_mongo_document(transaction)

@router.post("/", status_code=status.HTTP_201_CREATED, response_model=TransactionResponse)
async def create_transaction(
    transaction_data: TransactionCreate,
    token: str = Depends(oauth2_scheme)
):
    """
    Create a new manual transaction
    """
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"Creating transaction: {transaction_data.dict()}")
    
    try:
        user_id = await get_current_user_id(token)
        
        # Verify user ID matches the requested user_id for security
        if user_id != transaction_data.user_id:
            raise UnauthorizedException(detail="User ID mismatch")
        
        # Check if account exists and belongs to user
        accounts_collection = await get_collection("accounts")
        
        # Handle different ID formats
        try:
            object_account_id = ObjectId(transaction_data.account_id)
        except:
            object_account_id = transaction_data.account_id
        
        try:
            object_user_id = ObjectId(user_id)
        except:
            object_user_id = user_id
            
        # Try multiple query formats
        account_queries = [
            {"_id": object_account_id, "user_id": object_user_id},
            {"_id": object_account_id, "user_id": user_id},
            {"_id": object_account_id, "user_id": str(object_user_id)},
            {"id": transaction_data.account_id, "user_id": user_id}
        ]
        
        account = None
        for query in account_queries:
            try:
                account = await accounts_collection.find_one(query)
                if account:
                    logger.info(f"Found account with query: {query}")
                    break
            except Exception as e:
                logger.error(f"Error querying with {query}: {str(e)}")
        
        if not account:
            logger.error(f"Account not found: {transaction_data.account_id}")
            raise NotFoundException(detail="Account not found")
        
        # Create transaction with ID
        transaction_id = str(ObjectId())
        
        # Convert merchant data from MerchantBase to MerchantInfo if present
        merchant_info = None
        if transaction_data.merchant:
            merchant_dict = transaction_data.merchant.dict()
            # Create MerchantInfo instance with the correct fields
            from app.models.transaction import MerchantInfo
            merchant_info = MerchantInfo(**merchant_dict)
        
        # Convert location data if present
        location_info = None
        if transaction_data.location:
            location_dict = transaction_data.location.dict()
            from app.models.transaction import Location
            location_info = Location(**location_dict)
        
        transaction = Transaction(
            id=transaction_id,
            user_id=user_id,
            account_id=transaction_data.account_id,
            amount=transaction_data.amount,
            transaction_type=transaction_data.transaction_type,
            description=transaction_data.description,
            original_description=transaction_data.original_description or transaction_data.description,
            date=transaction_data.date,
            category=transaction_data.category or TransactionCategory.UNKNOWN,
            subcategory=transaction_data.subcategory,
            tags=transaction_data.tags or [],
            merchant=merchant_info,  # Use the converted merchant_info
            location=location_info,  # Use the converted location_info
            notes=transaction_data.notes,
            is_manual=True,
            source="manual",
            tax_relevant=transaction_data.tax_relevant or False,
            tax_category=transaction_data.tax_category
        )
        
        # Insert transaction into database
        transactions_collection = await get_collection("transactions")
        transaction_dict = transaction.dict()
        
        # Set _id field for MongoDB
        transaction_dict["_id"] = ObjectId(transaction_id)
        
        result = await transactions_collection.insert_one(transaction_dict)
        logger.info(f"Transaction created with ID: {result.inserted_id}")
        
        # Get created transaction
        created_transaction = await transactions_collection.find_one({"_id": result.inserted_id})
        if not created_transaction:
            logger.error(f"Could not find created transaction with ID: {result.inserted_id}")
            raise BadRequestException(detail="Transaction created but could not be retrieved")
        
        # Update account balance based on transaction
        try:
            await update_account_balance_from_transaction(
                account_id=transaction_data.account_id,
                amount=transaction_data.amount,
                transaction_type=transaction_data.transaction_type
            )
        except Exception as balance_error:
            logger.error(f"Error updating account balance: {str(balance_error)}")
            # Don't fail the whole transaction if balance update fails
            # You may want to add a flag in the response indicating this
        
        return convert_mongo_document(created_transaction)
        
    except Exception as e:
        logger.error(f"Error creating transaction: {str(e)}", exc_info=True)
        if isinstance(e, (NotFoundException, UnauthorizedException, BadRequestException)):
            raise e
        raise BadRequestException(detail=f"Error creating transaction: {str(e)}")

@router.put("/{transaction_id}", response_model=TransactionResponse)
async def update_transaction(
    transaction_data: TransactionUpdate,
    transaction_id: str = Path(..., description="Transaction ID"),
    token: str = Depends(oauth2_scheme)
):
    """
    Update a transaction's details
    """
    user_id = await get_current_user_id(token)
    
    # Get transaction from database
    transactions_collection = await get_collection("transactions")
    
    # Try both string ID and MongoDB ObjectId
    transaction = None
    object_id = None
    
    # First try with string ID
    transaction = await transactions_collection.find_one({
        "user_id": user_id,
        "$or": [
            {"id": transaction_id},
            {"transaction_id": transaction_id}
        ]
    })
    
    # If not found, try with ObjectId
    if not transaction:
        try:
            object_id = ObjectId(transaction_id)
            transaction = await transactions_collection.find_one({
                "_id": object_id,
                "user_id": user_id
            })
        except Exception:
            pass
    
    if not transaction:
        raise NotFoundException(detail="Transaction not found")
    
    # Remember the original data for balance adjustment
    original_amount = transaction["amount"]
    original_type = transaction["transaction_type"]
    
    # Prepare update data
    update_data = {}
    for field, value in transaction_data.dict(exclude_unset=True).items():
        if value is not None:
            update_data[field] = value
    
    update_data["updated_at"] = get_current_time_ist()
    
    # Use the ID format that worked
    if object_id:
        update_query = {"_id": object_id}
    else:
        update_query = {"$or": [{"id": transaction_id}, {"transaction_id": transaction_id}]}
    
    # Update transaction
    await transactions_collection.update_one(
        update_query,
        {"$set": update_data}
    )
    
    # Get updated transaction
    updated_transaction = await transactions_collection.find_one(update_query)
    
    # If amount or transaction_type has changed, update account balance
    if (("amount" in update_data and update_data["amount"] != original_amount) or 
            ("transaction_type" in update_data and update_data["transaction_type"] != original_type)):
        # First reverse the original transaction's effect
        await update_account_balance_from_transaction(
            account_id=transaction["account_id"],
            amount=original_amount,
            transaction_type=original_type,
            reverse=True
        )
        # Then apply the new transaction's effect
        await update_account_balance_from_transaction(
            account_id=transaction["account_id"],
            amount=update_data.get("amount", original_amount),
            transaction_type=update_data.get("transaction_type", original_type)
        )
    
    return convert_mongo_document(updated_transaction)

@router.put("/{transaction_id}/category", response_model=TransactionResponse)
async def update_transaction_category(
    transaction_id: str = Path(..., description="Transaction ID"),
    category: TransactionCategory = Query(..., description="New category"),
    subcategory: Optional[str] = Query(None, description="New subcategory"),
    token: str = Depends(oauth2_scheme)
):
    """
    Update a transaction's category
    """
    user_id = await get_current_user_id(token)
    
    # Get transaction from database
    transactions_collection = await get_collection("transactions")
    
    # Try both string ID and MongoDB ObjectId
    transaction = None
    object_id = None
    
    # First try with string ID
    transaction = await transactions_collection.find_one({
        "user_id": user_id,
        "$or": [
            {"id": transaction_id},
            {"transaction_id": transaction_id}
        ]
    })
    
    # If not found, try with ObjectId
    if not transaction:
        try:
            object_id = ObjectId(transaction_id)
            transaction = await transactions_collection.find_one({
                "_id": object_id,
                "user_id": user_id
            })
        except Exception:
            pass
    
    if not transaction:
        raise NotFoundException(detail="Transaction not found")
    
    # Prepare update data
    update_data = {
        "category": category,
        "updated_at": get_current_time_ist()
    }
    
    if subcategory:
        update_data["subcategory"] = subcategory
    
    # Use the ID format that worked
    if object_id:
        update_query = {"_id": object_id}
    else:
        update_query = {"$or": [{"id": transaction_id}, {"transaction_id": transaction_id}]}
    
    # Update transaction
    await transactions_collection.update_one(
        update_query,
        {"$set": update_data}
    )
    
    # Get updated transaction
    updated_transaction = await transactions_collection.find_one(update_query)
    
    return convert_mongo_document(updated_transaction)

@router.delete("/{transaction_id}", status_code=status.HTTP_200_OK)
async def delete_transaction(
    transaction_id: str = Path(..., description="Transaction ID"),
    token: str = Depends(oauth2_scheme)
):
    """
    Delete a transaction
    """
    user_id = await get_current_user_id(token)
    
    # Get transaction from database
    transactions_collection = await get_collection("transactions")
    
    # Try both string ID and MongoDB ObjectId
    transaction = None
    object_id = None
    
    # First try with string ID
    transaction = await transactions_collection.find_one({
        "user_id": user_id,
        "$or": [
            {"id": transaction_id},
            {"transaction_id": transaction_id}
        ]
    })
    
    # If not found, try with ObjectId
    if not transaction:
        try:
            object_id = ObjectId(transaction_id)
            transaction = await transactions_collection.find_one({
                "_id": object_id,
                "user_id": user_id
            })
        except Exception:
            pass
    
    if not transaction:
        raise NotFoundException(detail="Transaction not found")
    
    # Use the ID format that worked
    if object_id:
        delete_query = {"_id": object_id}
    else:
        delete_query = {"$or": [{"id": transaction_id}, {"transaction_id": transaction_id}]}
    
    # Delete transaction
    await transactions_collection.delete_one(delete_query)
    
    # Reverse the transaction's effect on account balance
    await update_account_balance_from_transaction(
        account_id=transaction["account_id"],
        amount=transaction["amount"],
        transaction_type=transaction["transaction_type"],
        reverse=True
    )
    
    return {"success": True, "message": "Transaction deleted successfully"}



@router.post("/split", status_code=status.HTTP_200_OK, response_model=List[TransactionResponse])
async def split_transaction(
    split_data: SplitTransactionRequest,
    token: str = Depends(oauth2_scheme)
):
    """
    Split a transaction into multiple parts with different categories
    """
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"Processing transaction split request for {split_data.transaction_id}")
    
    user_id = await get_current_user_id(token)
    
    # Get original transaction
    transactions_collection = await get_collection("transactions")
    
    # Try both string ID and MongoDB ObjectId
    transaction = None
    object_id = None
    transaction_id = split_data.transaction_id
    
    # First try with string ID
    transaction = await transactions_collection.find_one({
        "user_id": user_id,
        "$or": [
            {"id": transaction_id},
            {"transaction_id": transaction_id}
        ]
    })
    
    # If not found, try with ObjectId
    if not transaction:
        try:
            object_id = ObjectId(transaction_id)
            transaction = await transactions_collection.find_one({
                "_id": object_id,
                "user_id": user_id
            })
        except Exception:
            pass
    
    if not transaction:
        raise NotFoundException(detail="Transaction not found")
    
    # Check if transaction is already split
    if transaction.get("is_split", False):
        raise BadRequestException(detail="Transaction is already split")
    
    # Validate split amounts sum to the original amount
    total_split_amount = sum(split.amount for split in split_data.splits)
    if abs(total_split_amount - transaction["amount"]) > 0.01:  # Allow small rounding differences
        raise BadRequestException(detail="Total split amounts must equal the original transaction amount")
    
    # Mark original transaction as split
    if object_id:
        update_query = {"_id": object_id}
    else:
        update_query = {"$or": [{"id": transaction_id}, {"transaction_id": transaction_id}]}
    
    # Important fix: Update the original transaction with is_split=True
    await transactions_collection.update_one(
        update_query,
        {
            "$set": {
                "is_split": True,
                "updated_at": get_current_time_ist()
            }
        }
    )
    
    # Create split transactions
    split_transactions = []
    split_transaction_ids = []
    
    for split in split_data.splits:
        # Generate unique IDs for the split transactions
        split_id = str(ObjectId())
        split_transaction_id = f"TXN_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"
        
        # Create a copy of merchant and location if they exist
        merchant_info = None
        if transaction.get("merchant"):
            from app.models.transaction import MerchantInfo
            merchant_dict = transaction["merchant"].copy()
            merchant_info = MerchantInfo(**merchant_dict)
        
        location_info = None
        if transaction.get("location"):
            from app.models.transaction import Location
            location_dict = transaction["location"].copy()
            location_info = Location(**location_dict)
        
        # Create new transaction based on original
        split_transaction = Transaction(
            id=split_id,
            transaction_id=split_transaction_id,
            user_id=transaction["user_id"],
            account_id=transaction["account_id"],
            amount=split.amount,
            transaction_type=transaction["transaction_type"],
            description=f"{split.description or transaction['description']} (Split)",
            original_description=transaction["original_description"],
            date=transaction["date"],
            category=split.category,
            subcategory=split.subcategory,
            tags=split.tags or transaction.get("tags", []),
            merchant=merchant_info,
            location=location_info,
            is_manual=False,
            source="split",
            parent_transaction_id=transaction_id,
            status=TransactionStatus.COMPLETED
        )
        
        split_transaction_dict = split_transaction.dict()
        split_transaction_dict["_id"] = ObjectId(split_id)
        
        # Insert into database
        result = await transactions_collection.insert_one(split_transaction_dict)
        split_transaction_ids.append(str(result.inserted_id))
        
        created_split = await transactions_collection.find_one({"_id": result.inserted_id})
        if not created_split:
            logger.error(f"Failed to retrieve created split transaction: {result.inserted_id}")
            continue
            
        split_transactions.append(convert_mongo_document(created_split))
    
    # Log successful split
    logger.info(f"Transaction {transaction_id} split into {len(split_transactions)} parts: {split_transaction_ids}")
    
    return split_transactions

# Helper function to update account balance based on transaction
async def update_account_balance_from_transaction(
    account_id: str,
    amount: float,
    transaction_type: TransactionType,
    reverse: bool = False
):
    """Update account balance based on transaction"""
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"Updating balance for account {account_id}: amount={amount}, type={transaction_type}, reverse={reverse}")
    
    accounts_collection = await get_collection("accounts")
    
    # Try different account ID formats
    account = None
    
    # Try with ObjectId
    try:
        object_account_id = ObjectId(account_id)
        account = await accounts_collection.find_one({"_id": object_account_id})
    except Exception:
        pass
        
    # If not found, try with string ID
    if not account:
        try:
            account = await accounts_collection.find_one({"_id": account_id})
        except Exception:
            pass
            
    # If still not found, try with the "id" field
    if not account:
        try:
            account = await accounts_collection.find_one({"id": account_id})
        except Exception:
            pass
    
    if not account:
        logger.error(f"Account not found for balance update: {account_id}")
        raise NotFoundException(detail=f"Account not found for balance update: {account_id}")
    
    # Calculate balance change
    balance_change = amount
    
    # Apply the reverse if needed
    if reverse:
        balance_change = -balance_change
    
    # Adjust balance based on transaction type
    if transaction_type == TransactionType.DEBIT:
        # For debits, subtract from balance
        balance_change = -balance_change
    
    # Update account balance
    try:
        result = await accounts_collection.update_one(
            {"_id": account["_id"]},
            {
                "$inc": {"current_balance": balance_change},
                "$set": {"last_balance_update": get_current_time_ist()}
            }
        )
        logger.info(f"Balance updated for account {account_id}: change={balance_change}, modified_count={result.modified_count}")
        return True
    except Exception as e:
        logger.error(f"Failed to update account balance: {str(e)}")
        raise ExternalAPIException(detail=f"Failed to update account balance: {str(e)}")