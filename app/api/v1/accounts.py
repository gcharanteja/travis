from typing import Dict, List, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Path, Query
from bson import ObjectId

from app.config.database import get_collection
from app.config.settings import get_settings
from app.core.security import oauth2_scheme, decode_access_token
from app.core.exceptions import NotFoundException, UnauthorizedException, ExternalAPIException, BadRequestException
from app.schemas.account import (
    AccountResponse, 
    AccountSummaryResponse, 
    AccountsByTypeResponse, 
    PlaidLinkRequest,
    PlaidLinkResponse,
    PlaidExchangeRequest,
    AccountCreate,
    AccountUpdate,
    RefreshAccountRequest
)
from app.models.account import Account, AccountStatus
from app.utils.helpers import get_current_time_ist, convert_mongo_document

# Import mock bank service instead of Plaid
from app.services.mock_bank_service import (
    create_link_token,
    exchange_public_token,
    fetch_account_transactions,
    update_account_balance,
    disconnect_account,
    refresh_all_accounts
)

# Get settings
settings = get_settings()

router = APIRouter(
    prefix="/accounts",
    tags=["accounts"],
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

@router.get("", response_model=List[AccountSummaryResponse])
async def list_accounts(
    token: str = Depends(oauth2_scheme),
    status: Optional[str] = Query(None, description="Filter by account status"),
    account_type: Optional[str] = Query(None, description="Filter by account type")
):
    """
    List all accounts for the current user
    
    - **status**: Filter by account status (active, pending, error, disconnected)
    - **account_type**: Filter by account type (savings, current, credit_card, etc.)
    """
    user_id = await get_current_user_id(token)
    
    # Build filter
    filter_query = {"user_id": user_id}
    if status:
        filter_query["status"] = status
    if account_type:
        filter_query["account_type"] = account_type
    
    # Get accounts from database
    accounts_collection = await get_collection("accounts")
    accounts = await accounts_collection.find(filter_query).to_list(length=100)
    
    # Convert to response model
    result = [convert_mongo_document(account) for account in accounts]
    
    return result

@router.get("/by-type", response_model=AccountsByTypeResponse)
async def list_accounts_by_type(token: str = Depends(oauth2_scheme)):
    """
    List all accounts for the current user, grouped by account type
    """
    user_id = await get_current_user_id(token)
    
    # Get accounts from database
    accounts_collection = await get_collection("accounts")
    accounts = await accounts_collection.find({
        "user_id": user_id,
        "status": {"$ne": AccountStatus.DELETED}
    }).to_list(length=100)
    
    # Group accounts by type
    result = AccountsByTypeResponse(
        savings=[],
        current=[],
        credit_card=[],
        loan=[],
        investment=[],
        other=[]
    )
    
    total_balance = 0
    
    for account in accounts:
        account_data = convert_mongo_document(account)
        account_summary = AccountSummaryResponse(**account_data)
        
        # Add to appropriate list based on account type
        if account["account_type"] == "savings":
            result.savings.append(account_summary)
            # Add positive balances to total
            total_balance += account["current_balance"] if account["current_balance"] > 0 else 0
            
        elif account["account_type"] == "current":
            result.current.append(account_summary)
            # Add positive balances to total
            total_balance += account["current_balance"] if account["current_balance"] > 0 else 0
            
        elif account["account_type"] == "credit_card":
            result.credit_card.append(account_summary)
            # Don't add credit card balances to total
            
        elif account["account_type"] == "loan":
            result.loan.append(account_summary)
            # Don't add loan balances to total
            
        elif account["account_type"] in ["fixed_deposit", "recurring_deposit", "demat", "mutual_fund", "ppf", "epf", "nps"]:
            result.investment.append(account_summary)
            # Add investment balances to total
            total_balance += account["current_balance"] if account["current_balance"] > 0 else 0
            
        else:
            result.other.append(account_summary)
            # Add other positive balances to total
            total_balance += account["current_balance"] if account["current_balance"] > 0 else 0
    
    result.total_balance = total_balance
    
    return result

@router.get("/{account_id}", response_model=AccountResponse)
async def get_account(
    account_id: str = Path(..., description="Account ID"),
    token: str = Depends(oauth2_scheme)
):
    """
    Get account details by ID
    """
    import logging
    logger = logging.getLogger(__name__)
    
    user_id = await get_current_user_id(token)
    
    # Get account from database
    accounts_collection = await get_collection("accounts")
    
    # Convert string ID to MongoDB ObjectId
    try:
        object_account_id = ObjectId(account_id)
    except Exception as e:
        logger.error(f"Invalid account ID format: {account_id}, error: {str(e)}")
        raise NotFoundException(detail="Invalid account ID format")
    
    # Try with different ID formats for user_id
    try:
        object_user_id = ObjectId(user_id)
    except:
        object_user_id = user_id
    
    # Try all possible combinations of ID formats
    account_queries = [
        {"_id": object_account_id, "user_id": object_user_id},
        {"_id": object_account_id, "user_id": user_id},
        {"_id": object_account_id, "user_id": str(object_user_id)},
        # Also try with string ID (although this shouldn't work with MongoDB)
        {"_id": account_id, "user_id": user_id}
    ]
    
    account = None
    for query in account_queries:
        try:
            logger.debug(f"Trying query: {query}")
            account = await accounts_collection.find_one(query)
            if account:
                logger.debug(f"Found account with query: {query}")
                break
        except Exception as e:
            logger.error(f"Error querying with {query}: {str(e)}")
    
    if not account:
        raise NotFoundException(detail="Account not found")
    
    return convert_mongo_document(account)

@router.post("/link/token", response_model=PlaidLinkResponse)
async def create_account_link_token(
    request: PlaidLinkRequest,
    token: str = Depends(oauth2_scheme)
):
    """
    Create a token for linking bank accounts using Plaid
    """
    user_id = await get_current_user_id(token)
    
    # Verify user ID matches the requested user_id for security
    if user_id != request.user_id:
        raise UnauthorizedException(detail="User ID mismatch")
    
    # Create link token using mock bank service (instead of Plaid)
    link_token_response = await create_link_token(user_id)
    
    return PlaidLinkResponse(
        link_token=link_token_response["link_token"],
        expiration=link_token_response["expiration"]
    )

@router.post("/link/exchange", status_code=status.HTTP_201_CREATED)
async def exchange_bank_token(
    request: PlaidExchangeRequest,
    token: str = Depends(oauth2_scheme)
):
    """
    Exchange public token for access token and create accounts
    """
    user_id = await get_current_user_id(token)
    
    # Verify user ID matches the requested user_id for security
    if user_id != request.user_id:
        raise UnauthorizedException(detail="User ID mismatch")
    
    # Exchange token using mock bank service (instead of Plaid)
    result = await exchange_public_token(request.public_token, user_id)
    
    return result

@router.delete("/{account_id}", status_code=status.HTTP_200_OK)
async def unlink_account(
    account_id: str = Path(..., description="Account ID"),
    token: str = Depends(oauth2_scheme)
):
    """
    Disconnect/unlink a bank account
    """
    user_id = await get_current_user_id(token)
    
    # Check if account exists and belongs to user
    accounts_collection = await get_collection("accounts")
    
    # Convert string ID to MongoDB ObjectId
    try:
        object_account_id = ObjectId(account_id)
    except:
        raise NotFoundException(detail="Invalid account ID format")
    
    # Try with different ID formats for user_id
    try:
        object_user_id = ObjectId(user_id)
    except:
        object_user_id = user_id
    
    # Try with ObjectId
    account = await accounts_collection.find_one({
        "_id": object_account_id,
        "user_id": object_user_id
    })
    
    # If not found, try with string user_id
    if not account:
        account = await accounts_collection.find_one({
            "_id": object_account_id,
            "user_id": user_id
        })
    
    if not account:
        raise NotFoundException(detail="Account not found")
    
    # Disconnect account using mock bank service
    result = await disconnect_account(str(object_account_id))
    
    return {"success": result, "message": "Account disconnected successfully"}

@router.get("/{account_id}/balance", status_code=status.HTTP_200_OK)
async def get_account_balance(
    account_id: str = Path(..., description="Account ID"),
    token: str = Depends(oauth2_scheme)
):
    """
    Get the latest balance for an account
    """
    import logging
    logger = logging.getLogger(__name__)
    
    user_id = await get_current_user_id(token)
    
    # Check if account exists and belongs to user
    accounts_collection = await get_collection("accounts")
    
    # Convert string ID to MongoDB ObjectId
    try:
        object_account_id = ObjectId(account_id)
    except Exception as e:
        logger.error(f"Invalid account ID format: {account_id}, error: {str(e)}")
        raise NotFoundException(detail="Invalid account ID format")
    
    # Try with different ID formats for user_id
    try:
        object_user_id = ObjectId(user_id)
    except:
        object_user_id = user_id
    
    # Try all possible combinations of ID formats
    account_queries = [
        {"_id": object_account_id, "user_id": object_user_id},
        {"_id": object_account_id, "user_id": user_id},
        {"_id": object_account_id, "user_id": str(object_user_id)}
    ]
    
    account = None
    for query in account_queries:
        try:
            account = await accounts_collection.find_one(query)
            if account:
                break
        except Exception as e:
            logger.error(f"Error querying with {query}: {str(e)}")
    
    if not account:
        raise NotFoundException(detail="Account not found")
    
    # Update account balance using mock bank service (instead of Plaid)
    try:
        balance_data = await update_account_balance(str(object_account_id))
        return balance_data
    except Exception as e:
        logger.error(f"Error updating balance: {str(e)}")
        raise ExternalAPIException(detail=f"Error updating balance: {str(e)}")

@router.post("/{account_id}/transactions/refresh", status_code=status.HTTP_200_OK)
async def refresh_account_transactions(
    account_id: str = Path(..., description="Account ID"),
    token: str = Depends(oauth2_scheme)
):
    """
    Refresh transactions for a specific account
    """
    import logging
    logger = logging.getLogger(__name__)
    
    user_id = await get_current_user_id(token)
    
    # Check if account exists and belongs to user
    accounts_collection = await get_collection("accounts")
    
    # Convert string ID to MongoDB ObjectId
    try:
        object_account_id = ObjectId(account_id)
    except Exception as e:
        logger.error(f"Invalid account ID format: {account_id}, error: {str(e)}")
        raise NotFoundException(detail="Invalid account ID format")
    
    # Try with different ID formats for user_id
    try:
        object_user_id = ObjectId(user_id)
    except:
        object_user_id = user_id
    
    # Try all possible combinations
    account_queries = [
        {"_id": object_account_id, "user_id": object_user_id},
        {"_id": object_account_id, "user_id": user_id},
        {"_id": object_account_id, "user_id": str(object_user_id)}
    ]
    
    account = None
    for query in account_queries:
        try:
            account = await accounts_collection.find_one(query)
            if account:
                break
        except Exception as e:
            logger.error(f"Error querying with {query}: {str(e)}")
    
    if not account:
        raise NotFoundException(detail="Account not found")
    
    # Update account transactions using mock bank service
    try:
        result = await fetch_account_transactions(str(object_account_id))
        return result
    except Exception as e:
        logger.error(f"Error refreshing transactions: {str(e)}")
        raise ExternalAPIException(detail=f"Error refreshing transactions: {str(e)}")

@router.post("/refresh-all", status_code=status.HTTP_200_OK)
async def refresh_all_user_accounts(token: str = Depends(oauth2_scheme)):
    """
    Refresh all accounts and transactions for the current user
    """
    user_id = await get_current_user_id(token)
    
    # Refresh all accounts using mock bank service (instead of Plaid)
    result = await refresh_all_accounts(user_id)
    
    return result

@router.post("/manual", status_code=status.HTTP_201_CREATED, response_model=AccountResponse)
async def create_manual_account(
    account_data: AccountCreate,
    token: str = Depends(oauth2_scheme)
):
    """
    Manually create an account (non-bank account like cash)
    """
    import logging
    logger = logging.getLogger(__name__)
    
    user_id = await get_current_user_id(token)
    
    # Verify user ID matches the requested user_id for security
    if user_id != account_data.user_id:
        raise UnauthorizedException(detail="User ID mismatch")
    
    try:
        # Try to convert user_id to ObjectId if needed
        try:
            object_user_id = ObjectId(user_id)
            user_id_for_db = user_id  # Keep original format for consistency
        except:
            user_id_for_db = user_id
            
        # Create account
        account = Account(
            id=str(ObjectId()),  # Generate MongoDB-compatible ID
            user_id=user_id_for_db,
            account_name=account_data.account_name,
            account_type=account_data.account_type,
            account_number_mask=account_data.account_number_mask,
            ifsc_code=account_data.ifsc_code,
            institution_name=account_data.institution_name,
            current_balance=account_data.current_balance,
            available_balance=account_data.available_balance or account_data.current_balance,
            limit=account_data.limit,
            currency=account_data.currency,
            integration_type=account_data.integration_type,
            account_subtype=account_data.account_subtype,
            interest_rate=account_data.interest_rate,
            maturity_date=account_data.maturity_date,
            notes=account_data.notes
        )
        
        # Insert account into database
        accounts_collection = await get_collection("accounts")
        account_dict = account.dict()
        
        # Set _id field for MongoDB
        account_dict["_id"] = ObjectId(account.id)
        
        result = await accounts_collection.insert_one(account_dict)
        inserted_id = str(result.inserted_id)
        
        # Update user's account list
        users_collection = await get_collection("users")
        
        # Convert user_id to ObjectId for MongoDB query
        try:
            user_object_id = ObjectId(user_id)
        except:
            user_object_id = user_id
            
        await users_collection.update_one(
            {"_id": user_object_id},
            {"$push": {"account_ids": inserted_id}}
        )
        
        # Get created account
        created_account = await accounts_collection.find_one({"_id": result.inserted_id})
        
        return convert_mongo_document(created_account)
    except Exception as e:
        logger.error(f"Error creating manual account: {str(e)}")
        raise BadRequestException(detail=f"Error creating manual account: {str(e)}")

@router.put("/{account_id}", response_model=AccountResponse)
async def update_account_details(
    account_data: AccountUpdate,
    account_id: str = Path(..., description="Account ID"),
    token: str = Depends(oauth2_scheme)
):
    """
    Update account details (primarily for manual accounts)
    """
    import logging
    logger = logging.getLogger(__name__)
    
    user_id = await get_current_user_id(token)
    
    # Check if account exists and belongs to user
    accounts_collection = await get_collection("accounts")
    
    # Convert string ID to MongoDB ObjectId
    try:
        object_account_id = ObjectId(account_id)
    except Exception as e:
        logger.error(f"Invalid account ID format: {account_id}, error: {str(e)}")
        raise NotFoundException(detail="Invalid account ID format")
    
    # Try with different ID formats for user_id
    try:
        object_user_id = ObjectId(user_id)
    except:
        object_user_id = user_id
    
    # Try all possible combinations
    account_queries = [
        {"_id": object_account_id, "user_id": object_user_id},
        {"_id": object_account_id, "user_id": user_id},
        {"_id": object_account_id, "user_id": str(object_user_id)}
    ]
    
    account = None
    for query in account_queries:
        try:
            account = await accounts_collection.find_one(query)
            if account:
                break
        except Exception as e:
            logger.error(f"Error querying with {query}: {str(e)}")
    
    if not account:
        raise NotFoundException(detail="Account not found")
    
    # Prepare update data
    update_data = {}
    for field, value in account_data.dict(exclude_unset=True).items():
        if value is not None:
            update_data[field] = value
    
    # Add updated timestamp
    update_data["updated_at"] = get_current_time_ist()
    
    # Update account in database
    await accounts_collection.update_one(
        {"_id": object_account_id},
        {"$set": update_data}
    )
    
    # Get updated account
    updated_account = await accounts_collection.find_one({"_id": object_account_id})
    
    return convert_mongo_document(updated_account)

@router.post("/reset-status", status_code=status.HTTP_200_OK)
async def reset_account_status(token: str = Depends(oauth2_scheme)):
    """
    Reset all accounts in error status back to active status
    """
    user_id = await get_current_user_id(token)
    
    # Try with different ID formats for user_id
    try:
        object_user_id = ObjectId(user_id)
    except:
        object_user_id = user_id
    
    # Get accounts collection
    accounts_collection = await get_collection("accounts")
    
    # Try both user_id formats
    result1 = await accounts_collection.update_many(
        {"user_id": object_user_id, "status": AccountStatus.ERROR},
        {"$set": {"status": AccountStatus.ACTIVE, "refresh_error": None}}
    )
    
    result2 = await accounts_collection.update_many(
        {"user_id": str(object_user_id), "status": AccountStatus.ERROR},
        {"$set": {"status": AccountStatus.ACTIVE, "refresh_error": None}}
    )
    
    total_updated = result1.modified_count + result2.modified_count
    
    return {
        "status": "success",
        "accounts_updated": total_updated,
        "message": f"Reset {total_updated} accounts from error to active status"
    }