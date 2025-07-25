import logging
from typing import Dict, List, Optional, Any
from datetime import datetime

import plaid
from plaid.api import plaid_api
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.country_code import CountryCode
from plaid.model.products import Products
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.item_get_request import ItemGetRequest
from plaid.model.accounts_get_request import AccountsGetRequest
from plaid.model.transactions_get_request import TransactionsGetRequest
from plaid.model.transactions_get_request_options import TransactionsGetRequestOptions
from plaid.model.accounts_balance_get_request import AccountsBalanceGetRequest

from app.config.settings import get_settings
from app.config.database import get_collection
from app.core.exceptions import ExternalAPIException, NotFoundException
from app.models.account import Account, PlaidAccountMetadata, AccountStatus, AccountType
from app.models.transaction import (
    Transaction, 
    TransactionType, 
    TransactionCategory,
    TransactionStatus,
    MerchantInfo,
    Location
)
from app.utils.helpers import get_current_time_ist

# Get settings
settings = get_settings()

# Configure logger
logger = logging.getLogger(__name__)

# Initialize Plaid client
def get_plaid_client():
    """Get configured Plaid client"""
    configuration = plaid.Configuration(
        host=plaid.Environment.Sandbox if settings.PLAID_ENV == "sandbox" else 
             plaid.Environment.Development if settings.PLAID_ENV == "development" else
             plaid.Environment.Production,
        api_key={
            "clientId": settings.PLAID_CLIENT_ID,
            "secret": settings.PLAID_SECRET,
        }
    )
    api_client = plaid.ApiClient(configuration)
    return plaid_api.PlaidApi(api_client)

async def create_link_token(user_id: str) -> Dict[str, Any]:
    """
    Create a Plaid Link token for connecting bank accounts
    
    Args:
        user_id: User ID
        
    Returns:
        Dictionary with link token and expiration
        
    Raises:
        ExternalAPIException: If Plaid API call fails
    """
    try:
        # Find user to verify existence
        users_collection = await get_collection("users")
        user = await users_collection.find_one({"_id": user_id})
        
        if not user:
            raise NotFoundException(detail="User not found")
        
        client = get_plaid_client()
        
        # Create link token request
        request = LinkTokenCreateRequest(
            user=LinkTokenCreateRequestUser(
                client_user_id=user_id
            ),
            client_name="Fintech AI Platform",
            products=[Products("transactions"), Products("auth")],
            country_codes=[CountryCode("IN"), CountryCode("US")],
            language="en",
            # Customized for Indian users
            link_customization_name="indian_banks"
        )
        
        # Create link token
        response = client.link_token_create(request)
        
        return {
            "link_token": response["link_token"],
            "expiration": response["expiration"]
        }
    except plaid.ApiException as e:
        logger.error(f"Plaid API error: {str(e)}")
        raise ExternalAPIException(
            detail=f"Plaid service error: {e.body}",
            code="plaid_api_error"
        )
    except Exception as e:
        logger.error(f"Error creating link token: {str(e)}")
        raise ExternalAPIException(detail=str(e))

async def exchange_public_token(public_token: str, user_id: str) -> Dict[str, Any]:
    """
    Exchange public token for access token and create accounts
    
    Args:
        public_token: Public token from Plaid Link
        user_id: User ID
        
    Returns:
        Dictionary with status and accounts created
        
    Raises:
        ExternalAPIException: If Plaid API call fails
    """
    try:
        client = get_plaid_client()
        
        # Exchange public token for access token
        exchange_request = ItemPublicTokenExchangeRequest(
            public_token=public_token
        )
        exchange_response = client.item_public_token_exchange(exchange_request)
        
        access_token = exchange_response["access_token"]
        item_id = exchange_response["item_id"]
        
        # Get item information
        item_request = ItemGetRequest(access_token=access_token)
        item_response = client.item_get(item_request)
        institution_id = item_response["item"]["institution_id"]
        
        # Get accounts
        accounts_request = AccountsGetRequest(access_token=access_token)
        accounts_response = client.accounts_get(accounts_request)
        
        accounts_collection = await get_collection("accounts")
        users_collection = await get_collection("users")
        
        # Create accounts
        created_account_ids = []
        
        for plaid_account in accounts_response["accounts"]:
            # Map Plaid account type to internal account type
            account_type = map_plaid_account_type(
                plaid_account["type"], 
                plaid_account.get("subtype", "")
            )
            
            # Create account metadata
            account_metadata = PlaidAccountMetadata(
                access_token=access_token,
                item_id=item_id,
                institution_id=institution_id,
                institution_name=item_response["item"]["institution_id"],
                last_updated=get_current_time_ist(),
                status="active"
            )
            
            # Create account
            account = Account(
                user_id=user_id,
                account_name=plaid_account["name"],
                account_type=account_type,
                account_number_mask=plaid_account["mask"],
                institution_name=item_response["item"]["institution_id"],
                current_balance=plaid_account["balances"]["current"] or 0.0,
                available_balance=plaid_account["balances"].get("available"),
                limit=plaid_account["balances"].get("limit"),
                currency=plaid_account["balances"]["iso_currency_code"] or "INR",
                last_balance_update=get_current_time_ist(),
                status=AccountStatus.ACTIVE,
                integration_type="plaid",
                plaid_metadata=account_metadata,
                account_subtype=plaid_account.get("subtype", "")
            )
            
            # Insert account
            result = await accounts_collection.insert_one(account.dict())
            created_account_id = str(result.inserted_id)
            created_account_ids.append(created_account_id)
            
            # Update user's account list
            await users_collection.update_one(
                {"_id": user_id},
                {"$push": {"account_ids": created_account_id}}
            )
            
            # Fetch initial transactions
            await fetch_account_transactions(created_account_id)
        
        logger.info(f"Created {len(created_account_ids)} accounts for user {user_id}")
        
        return {
            "status": "success",
            "accounts_created": len(created_account_ids),
            "account_ids": created_account_ids
        }
    except plaid.ApiException as e:
        logger.error(f"Plaid API error: {str(e)}")
        raise ExternalAPIException(
            detail=f"Plaid service error: {e.body}",
            code="plaid_api_error"
        )
    except Exception as e:
        logger.error(f"Error exchanging public token: {str(e)}")
        raise ExternalAPIException(detail=str(e))

async def fetch_account_transactions(account_id: str, start_date: Optional[datetime] = None, end_date: Optional[datetime] = None) -> Dict[str, Any]:
    """
    Fetch transactions for an account
    
    Args:
        account_id: Account ID
        start_date: Start date for transactions (optional)
        end_date: End date for transactions (optional)
        
    Returns:
        Dictionary with transaction count
        
    Raises:
        NotFoundException: If account not found
        ExternalAPIException: If Plaid API call fails
    """
    try:
        accounts_collection = await get_collection("accounts")
        transactions_collection = await get_collection("transactions")
        
        # Get account
        account = await accounts_collection.find_one({"_id": account_id})
        if not account:
            raise NotFoundException(detail="Account not found")
        
        # Check if account is Plaid-connected
        if account.get("integration_type") != "plaid" or not account.get("plaid_metadata"):
            raise ExternalAPIException(
                detail="Account is not connected via Plaid",
                code="not_plaid_account"
            )
        
        # Get access token
        access_token = account["plaid_metadata"]["access_token"]
        client = get_plaid_client()
        
        # Default to last 30 days if dates not provided
        if not start_date:
            start_date = get_current_time_ist().replace(day=1)  # First day of current month
        
        if not end_date:
            end_date = get_current_time_ist()
        
        # Convert dates to string format required by Plaid
        start_date_str = start_date.strftime("%Y-%m-%d")
        end_date_str = end_date.strftime("%Y-%m-%d")
        
        # Create request
        options = TransactionsGetRequestOptions(
            include_personal_finance_category=True
        )
        
        request = TransactionsGetRequest(
            access_token=access_token,
            start_date=start_date_str,
            end_date=end_date_str,
            options=options
        )
        
        # Get transactions
        response = client.transactions_get(request)
        plaid_transactions = response["transactions"]
        
        # Process transactions
        transaction_count = 0
        user_id = account["user_id"]
        
        for plaid_transaction in plaid_transactions:
            # Map transaction type
            transaction_type = TransactionType.CREDIT if plaid_transaction["amount"] < 0 else TransactionType.DEBIT
            
            # Map category
            category = map_plaid_category(plaid_transaction.get("personal_finance_category", {}).get("primary", ""))
            subcategory = plaid_transaction.get("personal_finance_category", {}).get("detailed", "")
            
            # Create merchant info if available
            merchant_info = None
            if plaid_transaction.get("merchant_name"):
                merchant_info = MerchantInfo(
                    name=plaid_transaction["merchant_name"],
                    category=plaid_transaction.get("category", ["unknown"])[0] if plaid_transaction.get("category") else None
                )
            
            # Create location info if available
            location_info = None
            if plaid_transaction.get("location"):
                loc = plaid_transaction["location"]
                location_info = Location(
                    city=loc.get("city"),
                    state=loc.get("region"),
                    country=loc.get("country"),
                    postal_code=loc.get("postal_code"),
                    address=loc.get("address")
                )
            
            # Create transaction
            transaction = Transaction(
                user_id=user_id,
                account_id=account_id,
                amount=abs(plaid_transaction["amount"]),
                currency=plaid_transaction.get("iso_currency_code", "INR"),
                transaction_type=transaction_type,
                status=TransactionStatus.COMPLETED,
                category=category,
                subcategory=subcategory,
                description=plaid_transaction["name"],
                original_description=plaid_transaction["name"],
                merchant=merchant_info,
                location=location_info,
                date=datetime.strptime(plaid_transaction["date"], "%Y-%m-%d"),
                posted_date=datetime.strptime(plaid_transaction["date"], "%Y-%m-%d"),
                source="plaid",
                is_manual=False,
                fingerprint=plaid_transaction.get("transaction_id")
            )
            
            # Check for duplicate transaction by fingerprint
            existing_transaction = await transactions_collection.find_one({
                "fingerprint": transaction.fingerprint
            })
            
            # Skip if duplicate
            if existing_transaction:
                continue
            
            # Insert transaction
            await transactions_collection.insert_one(transaction.dict())
            transaction_count += 1
        
        # Update account balance
        await update_account_balance(account_id)
        
        logger.info(f"Fetched {transaction_count} transactions for account {account_id}")
        
        return {
            "status": "success",
            "transactions_added": transaction_count
        }
    except plaid.ApiException as e:
        logger.error(f"Plaid API error: {str(e)}")
        
        # Update account status if there's an error
        if account:
            await accounts_collection.update_one(
                {"_id": account_id},
                {
                    "$set": {
                        "status": AccountStatus.ERROR,
                        "refresh_error": str(e),
                        "refresh_status": "failed",
                        "last_refresh_attempt": get_current_time_ist()
                    }
                }
            )
        
        raise ExternalAPIException(
            detail=f"Plaid service error: {e.body}",
            code="plaid_api_error"
        )
    except Exception as e:
        logger.error(f"Error fetching transactions: {str(e)}")
        
        # Update account status if there's an error
        if account:
            await accounts_collection.update_one(
                {"_id": account_id},
                {
                    "$set": {
                        "refresh_error": str(e),
                        "refresh_status": "failed",
                        "last_refresh_attempt": get_current_time_ist()
                    }
                }
            )
        
        raise ExternalAPIException(detail=str(e))

async def update_account_balance(account_id: str) -> Dict[str, Any]:
    """
    Update account balance from Plaid
    
    Args:
        account_id: Account ID
        
    Returns:
        Dictionary with updated balance information
        
    Raises:
        NotFoundException: If account not found
        ExternalAPIException: If Plaid API call fails
    """
    try:
        accounts_collection = await get_collection("accounts")
        
        # Get account
        account = await accounts_collection.find_one({"_id": account_id})
        if not account:
            raise NotFoundException(detail="Account not found")
        
        # Check if account is Plaid-connected
        if account.get("integration_type") != "plaid" or not account.get("plaid_metadata"):
            raise ExternalAPIException(
                detail="Account is not connected via Plaid",
                code="not_plaid_account"
            )
        
        # Get access token
        access_token = account["plaid_metadata"]["access_token"]
        client = get_plaid_client()
        
        # Get balance
        request = AccountsBalanceGetRequest(access_token=access_token)
        response = client.accounts_balance_get(request)
        
        # Find matching account in response
        for plaid_account in response["accounts"]:
            if plaid_account["mask"] == account["account_number_mask"]:
                # Update balance
                await accounts_collection.update_one(
                    {"_id": account_id},
                    {
                        "$set": {
                            "current_balance": plaid_account["balances"]["current"] or 0.0,
                            "available_balance": plaid_account["balances"].get("available"),
                            "limit": plaid_account["balances"].get("limit"),
                            "last_balance_update": get_current_time_ist(),
                            "refresh_status": "success",
                            "last_refresh_attempt": get_current_time_ist()
                        }
                    }
                )
                
                logger.info(f"Updated balance for account {account_id}")
                
                return {
                    "status": "success",
                    "current_balance": plaid_account["balances"]["current"] or 0.0,
                    "available_balance": plaid_account["balances"].get("available"),
                    "last_updated": get_current_time_ist()
                }
        
        raise ExternalAPIException(
            detail="Account not found in Plaid response",
            code="plaid_account_not_found"
        )
    except plaid.ApiException as e:
        logger.error(f"Plaid API error: {str(e)}")
        
        # Update account status
        if account:
            await accounts_collection.update_one(
                {"_id": account_id},
                {
                    "$set": {
                        "refresh_error": str(e),
                        "refresh_status": "failed",
                        "last_refresh_attempt": get_current_time_ist()
                    }
                }
            )
        
        raise ExternalAPIException(
            detail=f"Plaid service error: {e.body}",
            code="plaid_api_error"
        )
    except Exception as e:
        logger.error(f"Error updating balance: {str(e)}")
        
        # Update account status
        if account:
            await accounts_collection.update_one(
                {"_id": account_id},
                {
                    "$set": {
                        "refresh_error": str(e),
                        "refresh_status": "failed",
                        "last_refresh_attempt": get_current_time_ist()
                    }
                }
            )
        
        raise ExternalAPIException(detail=str(e))

async def disconnect_account(account_id: str) -> bool:
    """
    Disconnect a Plaid-connected account
    
    Args:
        account_id: Account ID
        
    Returns:
        True if successful
        
    Raises:
        NotFoundException: If account not found
    """
    accounts_collection = await get_collection("accounts")
    
    # Get account
    account = await accounts_collection.find_one({"_id": account_id})
    if not account:
        raise NotFoundException(detail="Account not found")
    
    # Update account status
    await accounts_collection.update_one(
        {"_id": account_id},
        {
            "$set": {
                "status": AccountStatus.DISCONNECTED,
                "updated_at": get_current_time_ist()
            }
        }
    )
    
    logger.info(f"Disconnected account {account_id}")
    
    return True

async def refresh_all_accounts(user_id: str) -> Dict[str, Any]:
    """
    Refresh all Plaid-connected accounts for a user
    
    Args:
        user_id: User ID
        
    Returns:
        Dictionary with refresh status
        
    Raises:
        NotFoundException: If user not found
    """
    accounts_collection = await get_collection("accounts")
    
    # Find all active Plaid-connected accounts for the user
    accounts = await accounts_collection.find({
        "user_id": user_id,
        "integration_type": "plaid",
        "status": {"$in": [AccountStatus.ACTIVE, AccountStatus.ERROR]}
    }).to_list(length=100)
    
    if not accounts:
        return {
            "status": "success",
            "message": "No Plaid accounts to refresh",
            "accounts_updated": 0
        }
    
    # Refresh each account
    success_count = 0
    error_count = 0
    
    for account in accounts:
        try:
            # Update balance
            await update_account_balance(str(account["_id"]))
            
            # Fetch transactions
            await fetch_account_transactions(str(account["_id"]))
            
            success_count += 1
        except Exception as e:
            logger.error(f"Error refreshing account {account['_id']}: {str(e)}")
            error_count += 1
    
    logger.info(f"Refreshed {success_count} accounts for user {user_id}, {error_count} errors")
    
    return {
        "status": "success",
        "accounts_updated": success_count,
        "accounts_failed": error_count
    }

# Helper functions
def map_plaid_account_type(plaid_type: str, plaid_subtype: str) -> AccountType:
    """Map Plaid account type to internal account type"""
    # Mapping for main types
    type_mapping = {
        "depository": AccountType.SAVINGS,  # Default, will be refined by subtype
        "credit": AccountType.CREDIT_CARD,
        "loan": AccountType.LOAN,
        "investment": AccountType.DEMAT,
        "other": AccountType.OTHER
    }
    
    # Refine mapping based on subtype
    subtype_mapping = {
        "checking": AccountType.CURRENT,
        "savings": AccountType.SAVINGS,
        "cd": AccountType.FIXED_DEPOSIT,
        "money market": AccountType.SAVINGS,
        "paypal": AccountType.SAVINGS,
        "prepaid": AccountType.SAVINGS,
        "credit card": AccountType.CREDIT_CARD,
        "auto": AccountType.LOAN,
        "commercial": AccountType.LOAN,
        "construction": AccountType.LOAN,
        "consumer": AccountType.LOAN,
        "home": AccountType.LOAN,
        "home equity": AccountType.LOAN,
        "loan": AccountType.LOAN,
        "mortgage": AccountType.LOAN,
        "overdraft": AccountType.LOAN,
        "line of credit": AccountType.LOAN,
        "student": AccountType.LOAN,
        "mutual fund": AccountType.MUTUAL_FUND,
        "recurring deposit": AccountType.RECURRING_DEPOSIT,
        "fixed deposit": AccountType.FIXED_DEPOSIT,
        "ppf": AccountType.PPF,
        "epf": AccountType.EPF,
        "nps": AccountType.NPS
    }
    
    # Try to use subtype first, fall back to main type
    if plaid_subtype.lower() in subtype_mapping:
        return subtype_mapping[plaid_subtype.lower()]
    
    return type_mapping.get(plaid_type.lower(), AccountType.OTHER)

def map_plaid_category(plaid_category: str) -> TransactionCategory:
    """Map Plaid category to internal category"""
    category_mapping = {
        "FOOD_AND_DRINK": TransactionCategory.FOOD_DINING,
        "GENERAL_MERCHANDISE": TransactionCategory.SHOPPING,
        "HOME_IMPROVEMENT": TransactionCategory.HOUSING,
        "RENT": TransactionCategory.HOUSING,
        "MORTGAGE": TransactionCategory.HOUSING,
        "LOAN_PAYMENTS": TransactionCategory.LOAN,
        "TRANSPORTATION": TransactionCategory.TRANSPORTATION,
        "TRAVEL": TransactionCategory.TRAVEL,
        "GENERAL_SERVICES": TransactionCategory.OTHER,
        "ENTERTAINMENT": TransactionCategory.ENTERTAINMENT,
        "MEDICAL": TransactionCategory.HEALTHCARE,
        "EDUCATION": TransactionCategory.EDUCATION,
        "PERSONAL_CARE": TransactionCategory.PERSONAL_CARE,
        "UTILITIES": TransactionCategory.BILLS_UTILITIES,
        "INCOME": TransactionCategory.INCOME,
        "TRANSFER_IN": TransactionCategory.TRANSFER,
        "TRANSFER_OUT": TransactionCategory.TRANSFER,
        "LOAN": TransactionCategory.LOAN,
        "INSURANCE": TransactionCategory.INSURANCE,
        "TAX": TransactionCategory.TAX,
        "GIFT": TransactionCategory.GIFT,
        "CHARITABLE_GIVING": TransactionCategory.DONATION
    }
    
    return category_mapping.get(plaid_category, TransactionCategory.UNKNOWN)