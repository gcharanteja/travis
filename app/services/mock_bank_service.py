import logging
import random
import uuid
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from bson import ObjectId  # Add this import

from app.config.database import get_collection
from app.core.exceptions import ExternalAPIException, NotFoundException
from app.models.account import Account, AccountStatus, AccountType
from app.models.transaction import (
    Transaction, 
    TransactionType, 
    TransactionCategory,
    TransactionStatus,
    MerchantInfo,
    Location
)
from app.utils.helpers import get_current_time_ist

# Configure logger
logger = logging.getLogger(__name__)

# Mock bank data for generating realistic accounts
MOCK_BANKS = [
    {
        "name": "HDFC Bank",
        "institution_id": "IN_HDFC",
        "logo": "https://example.com/logos/hdfc.png",
        "color": "#004C8F",
        "account_types": ["savings", "current", "credit_card", "loan", "fixed_deposit"],
        "ifsc_prefix": "HDFC"
    },
    {
        "name": "ICICI Bank",
        "institution_id": "IN_ICICI",
        "logo": "https://example.com/logos/icici.png",
        "color": "#F58220",
        "account_types": ["savings", "current", "credit_card", "loan", "fixed_deposit"],
        "ifsc_prefix": "ICIC"
    },
    {
        "name": "SBI",
        "institution_id": "IN_SBI",
        "logo": "https://example.com/logos/sbi.png",
        "color": "#2D5DA0",
        "account_types": ["savings", "current", "credit_card", "loan", "fixed_deposit", "ppf"],
        "ifsc_prefix": "SBIN"
    },
    {
        "name": "Axis Bank",
        "institution_id": "IN_AXIS",
        "logo": "https://example.com/logos/axis.png",
        "color": "#97144D",
        "account_types": ["savings", "current", "credit_card", "loan"],
        "ifsc_prefix": "UTIB"
    },
    {
        "name": "Kotak Mahindra Bank",
        "institution_id": "IN_KOTAK",
        "logo": "https://example.com/logos/kotak.png",
        "color": "#EE1C25",
        "account_types": ["savings", "current", "credit_card"],
        "ifsc_prefix": "KKBK"
    }
]

# Mock merchants for generating realistic transactions
MOCK_MERCHANTS = [
    {"name": "Amazon", "category": "SHOPPING"},
    {"name": "Flipkart", "category": "SHOPPING"},
    {"name": "Swiggy", "category": "FOOD_AND_DRINK"},
    {"name": "Zomato", "category": "FOOD_AND_DRINK"},
    {"name": "BigBasket", "category": "GROCERIES"},
    {"name": "DMart", "category": "GROCERIES"},
    {"name": "Netflix", "category": "ENTERTAINMENT"},
    {"name": "BookMyShow", "category": "ENTERTAINMENT"},
    {"name": "MakeMyTrip", "category": "TRAVEL"},
    {"name": "IRCTC", "category": "TRAVEL"},
    {"name": "Ola", "category": "TRANSPORTATION"},
    {"name": "Uber", "category": "TRANSPORTATION"},
    {"name": "Apollo Pharmacy", "category": "MEDICAL"},
    {"name": "PharmEasy", "category": "MEDICAL"},
    {"name": "Reliance Digital", "category": "GENERAL_MERCHANDISE"},
    {"name": "Croma", "category": "GENERAL_MERCHANDISE"},
    {"name": "Urban Company", "category": "GENERAL_SERVICES"},
    {"name": "Vodafone Idea", "category": "UTILITIES"},
    {"name": "Airtel", "category": "UTILITIES"},
    {"name": "HDFC Credit Card", "category": "LOAN_PAYMENTS"},
    {"name": "SBI Home Loan", "category": "LOAN_PAYMENTS"},
    {"name": "LIC Premium", "category": "INSURANCE"},
    {"name": "Zerodha", "category": "INVESTMENTS"},
    {"name": "Groww", "category": "INVESTMENTS"},
    {"name": "Myntra", "category": "SHOPPING"},
    {"name": "Ajio", "category": "SHOPPING"}
]

# Common transaction descriptions for different categories
TRANSACTION_DESCRIPTIONS = {
    "FOOD_AND_DRINK": [
        "Food order", "Restaurant payment", "Coffee shop", "Dinner", "Lunch", "Breakfast", "Food delivery"
    ],
    "SHOPPING": [
        "Online shopping", "Store purchase", "Electronics", "Clothing", "Accessories", "Home goods"
    ],
    "GROCERIES": [
        "Grocery shopping", "Supermarket", "Fruits and vegetables", "Monthly groceries"
    ],
    "TRANSPORTATION": [
        "Taxi ride", "Cab fare", "Auto ride", "Petrol", "Diesel", "Vehicle service", "Parking fee"
    ],
    "ENTERTAINMENT": [
        "Movie tickets", "Subscription", "OTT platform", "Gaming", "Event tickets"
    ],
    "UTILITIES": [
        "Electricity bill", "Water bill", "Gas bill", "Internet bill", "Mobile recharge", "DTH recharge"
    ],
    "MEDICAL": [
        "Doctor consultation", "Medicine", "Lab test", "Hospital", "Health checkup"
    ]
}

# Cache to store mock tokens and access
# This simulates what would normally be stored in the Plaid system
MOCK_CACHE = {
    "link_tokens": {},  # user_id -> link_token data
    "access_tokens": {},  # access_token -> { item_id, user_id, institution }
    "accounts": {}  # access_token -> list of account data
}

async def create_link_token(user_id: str) -> Dict[str, Any]:
    """
    Create a mock link token for connecting bank accounts
    
    Args:
        user_id: User ID
        
    Returns:
        Dictionary with mock link token and expiration
        
    Raises:
        ExternalAPIException: If error simulation is triggered
        NotFoundException: If user not found
    """
    try:
        # Find user to verify existence
        users_collection = await get_collection("users")
        
        # Convert string ID to ObjectId
        user_object_id = ObjectId(user_id)
        
        user = await users_collection.find_one({"_id": user_object_id})
        
        if not user:
            raise NotFoundException(detail="User not found")
        
        # Simulate error occasionally to test error handling (1% chance)
        if random.random() < 0.01:
            raise Exception("Simulated link token creation error")
        
        # Generate mock link token and expiration
        link_token = f"mock_link_{uuid.uuid4().hex}"
        expiration = get_current_time_ist() + timedelta(hours=3)
        
        # Store in mock cache
        MOCK_CACHE["link_tokens"][user_id] = {
            "link_token": link_token,
            "expiration": expiration,
            "created_at": get_current_time_ist()
        }
        
        logger.info(f"Created mock link token for user {user_id}")
        
        return {
            "link_token": link_token,
            "expiration": expiration
        }
    except NotFoundException as e:
        raise e
    except Exception as e:
        logger.error(f"Error creating mock link token: {str(e)}")
        raise ExternalAPIException(
            detail=f"Mock bank service error: {str(e)}",
            code="mock_bank_api_error"
        )

async def exchange_public_token(public_token: str, user_id: str) -> Dict[str, Any]:
    """
    Exchange mock public token for access token and create accounts
    
    Args:
        public_token: Mock public token (in real app would come from frontend)
        user_id: User ID
        
    Returns:
        Dictionary with status and accounts created
        
    Raises:
        ExternalAPIException: If error simulation is triggered
    """
    try:
        # Determine how to handle the user_id
        try:
            user_object_id = ObjectId(user_id)
            # Convert to string for consistent storage
            user_id_for_storage = str(user_object_id)
        except:
            # If conversion fails, use as-is
            user_id_for_storage = user_id
        
        # Simulate error occasionally to test error handling (1% chance)
        if random.random() < 0.01:
            raise Exception("Simulated token exchange error")
        
        # Generate mock tokens
        access_token = f"mock_access_{uuid.uuid4().hex}"
        item_id = f"mock_item_{uuid.uuid4().hex}"
        
        # Select a random bank from our mock data
        selected_bank = random.choice(MOCK_BANKS)
        
        # Store the access token in our mock cache
        MOCK_CACHE["access_tokens"][access_token] = {
            "item_id": item_id,
            "user_id": user_id,
            "institution": selected_bank
        }
        
        # Generate 1-4 random accounts for this bank
        num_accounts = random.randint(1, 4)
        mock_accounts = []
        
        # Choose account types based on bank's supported types
        for _ in range(num_accounts):
            account_type_str = random.choice(selected_bank["account_types"])
            
            # Map to internal account type
            account_type = getattr(AccountType, account_type_str.upper(), AccountType.OTHER)
            
            # Generate a random 4-digit account mask
            account_mask = ''.join(random.choices('0123456789', k=4))
            
            # Generate balances based on account type
            if account_type == AccountType.CREDIT_CARD:
                current_balance = random.randint(500, 50000)
                available_balance = random.randint(10000, 100000) - current_balance
                limit = random.randint(50000, 500000) / 100.0 * 100
            elif account_type == AccountType.LOAN:
                current_balance = random.randint(100000, 5000000) / 100.0 * 100
                available_balance = None
                limit = None
            else:
                current_balance = random.randint(1000, 500000) / 100.0 * 100
                available_balance = current_balance - random.randint(0, min(50000, int(current_balance))) / 100.0 * 100
                limit = None
            
            mock_account = {
                "id": f"mock_acc_{uuid.uuid4().hex}",
                "name": f"{selected_bank['name']} {account_type.value.title()}",
                "type": account_type_str,
                "subtype": "",
                "mask": account_mask,
                "balances": {
                    "current": current_balance,
                    "available": available_balance,
                    "limit": limit,
                    "iso_currency_code": "INR"
                }
            }
            
            mock_accounts.append(mock_account)
        
        # Store accounts in cache
        MOCK_CACHE["accounts"][access_token] = mock_accounts
        
        accounts_collection = await get_collection("accounts")
        users_collection = await get_collection("users")
        
        # Create accounts in the database
        created_account_ids = []
        
        for mock_account in mock_accounts:
            # Create account metadata
            class MockMetadata:
                def __init__(self, access_token, item_id, bank):
                    self.access_token = access_token
                    self.item_id = item_id
                    self.institution_id = bank["institution_id"]
                    self.institution_name = bank["name"]
                    self.last_updated = get_current_time_ist()
                    self.status = "active"
                
                def dict(self):
                    return {
                        "access_token": self.access_token,
                        "item_id": self.item_id,
                        "institution_id": self.institution_id,
                        "institution_name": self.institution_name,
                        "last_updated": self.last_updated,
                        "status": self.status
                    }
            
            account_metadata = MockMetadata(access_token, item_id, selected_bank)
            
            # Create account
            account = Account(
                id=str(uuid.uuid4()),  # Make sure this generates a string ID
                user_id=user_id_for_storage,  # Use consistent format
                account_name=mock_account["name"],
                account_type=getattr(AccountType, mock_account["type"].upper(), AccountType.OTHER),
                account_number_mask=mock_account["mask"],
                institution_name=selected_bank["name"],
                institution_logo=selected_bank.get("logo"),
                institution_color=selected_bank.get("color"),
                current_balance=mock_account["balances"]["current"],
                available_balance=mock_account["balances"].get("available"),
                limit=mock_account["balances"].get("limit"),
                currency=mock_account["balances"].get("iso_currency_code", "INR"),
                last_balance_update=get_current_time_ist(),
                status=AccountStatus.ACTIVE,
                integration_type="mock_bank",
                plaid_metadata=account_metadata.dict(),  # Using plaid_metadata field for our mock data
                account_subtype=mock_account.get("subtype", "")
            )
            
            # Insert account
            result = await accounts_collection.insert_one(account.dict())
            created_account_id = str(result.inserted_id)  # Convert ObjectId to string
            created_account_ids.append(created_account_id)
            
            # Update user's account list
            await users_collection.update_one(
                {"_id": user_object_id},  # Use ObjectId for queries
                {"$push": {"account_ids": created_account_id}}
            )
            
            # Create initial transactions
            await fetch_account_transactions(created_account_id)
        
        logger.info(f"Created {len(created_account_ids)} mock accounts for user {user_id}")
        
        return {
            "status": "success",
            "accounts_created": len(created_account_ids),
            "account_ids": created_account_ids
        }
    except Exception as e:
        logger.error(f"Error exchanging mock public token: {str(e)}")
        raise ExternalAPIException(
            detail=f"Mock bank service error: {str(e)}",
            code="mock_bank_api_error"
        )

async def fetch_account_transactions(account_id: str, start_date: Optional[datetime] = None, end_date: Optional[datetime] = None) -> Dict[str, Any]:
    """
    Generate mock transactions for an account
    
    Args:
        account_id: Account ID
        start_date: Start date for transactions (optional)
        end_date: End date for transactions (optional)
        
    Returns:
        Dictionary with transaction count
        
    Raises:
        NotFoundException: If account not found
        ExternalAPIException: If error simulation is triggered
    """
    try:
        accounts_collection = await get_collection("accounts")
        transactions_collection = await get_collection("transactions")
        
        # Convert string ID to ObjectId when querying
        try:
            # Try to convert to ObjectId if it's not already
            object_account_id = ObjectId(account_id) if not isinstance(account_id, ObjectId) else account_id
        except:
            # If it fails, use the string ID
            object_account_id = account_id
        
        # Get account - try both ObjectId and string forms
        account = await accounts_collection.find_one({"_id": object_account_id})
        if not account:
            # Try with string ID as fallback
            account = await accounts_collection.find_one({"_id": account_id})
            if not account:
                raise NotFoundException(detail="Account not found")
        
        # Default to last 90 days if dates not provided
        if not end_date:
            end_date = get_current_time_ist()
        
        if not start_date:
            start_date = end_date - timedelta(days=90)
        
        # Generate a realistic number of transactions based on account type
        num_transactions = 0
        if account["account_type"] == AccountType.SAVINGS.value:
            num_transactions = random.randint(15, 40)  # Fewer transactions for savings
        elif account["account_type"] == AccountType.CURRENT.value:
            num_transactions = random.randint(40, 100)  # More transactions for current
        elif account["account_type"] == AccountType.CREDIT_CARD.value:
            num_transactions = random.randint(30, 80)  # Medium for credit cards
        else:
            num_transactions = random.randint(5, 20)  # Fewer for other types
        
        # Calculate date range
        date_range = (end_date - start_date).days
        
        # Generate transactions
        transaction_count = 0
        user_id = account["user_id"]
        
        # List to track used fingerprints to avoid duplication
        used_fingerprints = set()
        
        for _ in range(num_transactions):
            # Generate random transaction date within range
            days_offset = random.randint(0, date_range)
            transaction_date = start_date + timedelta(days=days_offset)
            
            # Select random merchant & category
            merchant = random.choice(MOCK_MERCHANTS)
            category = merchant["category"]
            
            # Determine transaction type (more debits than credits)
            is_credit = random.random() < 0.25  # 25% credits, 75% debits
            transaction_type = TransactionType.CREDIT if is_credit else TransactionType.DEBIT
            
            # Generate appropriate amount based on account type and transaction type
            if account["account_type"] == AccountType.CREDIT_CARD.value:
                amount = random.randint(100, 10000) / 100 * 100  # ₹100 to ₹10,000
            elif account["account_type"] == AccountType.CURRENT.value:
                amount = random.randint(500, 50000) / 100 * 100  # ₹500 to ₹50,000
            else:
                amount = random.randint(100, 5000) / 100 * 100  # ₹100 to ₹5,000
            
            # For credits (incoming money), adjust description and category
            if transaction_type == TransactionType.CREDIT:
                if random.random() < 0.7:  # 70% of credits are salary or transfers
                    merchant = {"name": "Salary" if random.random() < 0.5 else "Bank Transfer", "category": "INCOME"}
                    category = "INCOME"
                    amount = random.randint(10000, 100000) / 100 * 100  # ₹10,000 to ₹100,000
            
            # Map mock category to internal category
            internal_category = map_mock_category(category)
            
            # Generate description
            if category in TRANSACTION_DESCRIPTIONS:
                description = f"{merchant['name']} - {random.choice(TRANSACTION_DESCRIPTIONS[category])}"
            else:
                description = f"Payment to {merchant['name']}"
            
            # Create merchant info
            merchant_info = MerchantInfo(
                name=merchant["name"],
                category=category
            )
            
            # Create location info with a 50% chance
            location_info = None
            if random.random() < 0.5:
                cities = ["Mumbai", "Delhi", "Bangalore", "Chennai", "Hyderabad", "Pune", "Kolkata"]
                states = ["Maharashtra", "Delhi", "Karnataka", "Tamil Nadu", "Telangana", "West Bengal"]
                
                city = random.choice(cities)
                if city == "Mumbai" or city == "Pune":
                    state = "Maharashtra"
                elif city == "Delhi":
                    state = "Delhi"
                elif city == "Bangalore":
                    state = "Karnataka"
                elif city == "Chennai":
                    state = "Tamil Nadu"
                elif city == "Hyderabad":
                    state = "Telangana"
                elif city == "Kolkata":
                    state = "West Bengal"
                
                location_info = Location(
                    city=city,
                    state=state,
                    country="India",
                    postal_code=f"{random.randint(100000, 999999)}",
                    address=None
                )
            
            # Generate unique fingerprint
            fingerprint = f"mock_txn_{uuid.uuid4().hex}"
            while fingerprint in used_fingerprints:
                fingerprint = f"mock_txn_{uuid.uuid4().hex}"
            used_fingerprints.add(fingerprint)
            
            # Create transaction
            transaction = Transaction(
                user_id=user_id,
                account_id=account_id,
                amount=amount,
                currency="INR",
                transaction_type=transaction_type,
                status=TransactionStatus.COMPLETED,
                category=internal_category,
                subcategory=category,
                description=description,
                original_description=description,
                merchant=merchant_info,
                location=location_info,
                date=transaction_date,
                posted_date=transaction_date + timedelta(days=random.randint(0, 2)),  # Posted 0-2 days later
                source="mock_bank",
                is_manual=False,
                fingerprint=fingerprint
            )
            
            # Insert transaction
            await transactions_collection.insert_one(transaction.dict())
            transaction_count += 1
        
        # Update account balance based on recent transactions
        await update_account_balance(account_id)
        
        logger.info(f"Generated {transaction_count} mock transactions for account {account_id}")
        
        return {
            "status": "success",
            "transactions_added": transaction_count
        }
    except NotFoundException as e:
        raise e
    except Exception as e:
        logger.error(f"Error generating mock transactions: {str(e)}")
        
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
    Update account balance based on transactions
    
    Args:
        account_id: Account ID
        
    Returns:
        Dictionary with updated balance information
        
    Raises:
        NotFoundException: If account not found
        ExternalAPIException: If error simulation is triggered
    """
    try:
        accounts_collection = await get_collection("accounts")
        
        # Convert string ID to ObjectId when querying
        try:
            object_account_id = ObjectId(account_id) if not isinstance(account_id, ObjectId) else account_id
        except:
            object_account_id = account_id
        
        # Get account - try both forms
        account = await accounts_collection.find_one({"_id": object_account_id})
        if not account:
            account = await accounts_collection.find_one({"_id": account_id})
            if not account:
                raise NotFoundException(detail="Account not found")
        
        # Calculate current balance based on transactions
        # For simplicity in the mock service, we'll randomly adjust the balance slightly
        current_balance = account.get("current_balance", 0)
        
        # Small random adjustment (±5%)
        adjustment_factor = 1 + (random.random() * 0.1 - 0.05)
        new_balance = current_balance * adjustment_factor
        
        # For credit cards, ensure there's always a balance
        if account["account_type"] == AccountType.CREDIT_CARD.value and new_balance < 1000:
            new_balance = random.randint(1000, 10000)
        
        # Ensure positive balance for savings/current accounts
        if account["account_type"] in [AccountType.SAVINGS.value, AccountType.CURRENT.value] and new_balance < 0:
            new_balance = random.randint(100, 5000)
        
        # Calculate available balance
        if account["account_type"] == AccountType.CREDIT_CARD.value:
            limit = account.get("limit", 100000)
            available_balance = max(0, limit - new_balance)
        else:
            # For non-credit accounts, available might be slightly less than current
            available_factor = random.uniform(0.95, 1.0)
            available_balance = new_balance * available_factor
        
        # Update account balance
        await accounts_collection.update_one(
            {"_id": account_id},
            {
                "$set": {
                    "current_balance": new_balance,
                    "available_balance": available_balance,
                    "last_balance_update": get_current_time_ist(),
                    "refresh_status": "success",
                    "last_refresh_attempt": get_current_time_ist()
                }
            }
        )
        
        logger.info(f"Updated mock balance for account {account_id}")
        
        return {
            "status": "success",
            "current_balance": new_balance,
            "available_balance": available_balance,
            "last_updated": get_current_time_ist()
        }
    except NotFoundException as e:
        raise e
    except Exception as e:
        logger.error(f"Error updating mock balance: {str(e)}")
        
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
    Disconnect a mock bank-connected account
    """
    try:
        accounts_collection = await get_collection("accounts")
        
        # Try both string ID and ObjectId
        account = None
        
        # First try with string ID
        account = await accounts_collection.find_one({"_id": account_id})
        
        # If not found, try with ObjectId
        if not account:
            try:
                object_account_id = ObjectId(account_id)
                account = await accounts_collection.find_one({"_id": object_account_id})
            except Exception as e:
                logger.error(f"Invalid account ID format: {account_id}, error: {str(e)}")
                raise NotFoundException(detail="Invalid account ID format")
        
        if not account:
            raise NotFoundException(detail="Account not found")
        
        # Update account status - use the ID format that worked
        update_query = {"_id": account["_id"]}
        
        await accounts_collection.update_one(
            update_query,
            {
                "$set": {
                    "status": AccountStatus.DISCONNECTED,
                    "updated_at": get_current_time_ist()
                }
            }
        )
        
        logger.info(f"Disconnected mock account {account_id}")
        
        return True
    except Exception as e:
        if isinstance(e, NotFoundException):
            raise e
        logger.error(f"Error disconnecting account: {str(e)}")
        raise ExternalAPIException(
            detail=f"Error disconnecting account: {str(e)}",
            code="mock_bank_api_error"
        )

async def refresh_all_accounts(user_id: str) -> Dict[str, Any]:
    """
    Refresh all mock bank-connected accounts for a user
    """
    accounts_collection = await get_collection("accounts")
    
    # Try different user_id formats
    try:
        user_object_id = ObjectId(user_id)
    except:
        user_object_id = user_id
    
    # Create queries to try different combinations
    account_queries = [
        # Try with user_id as ObjectId, active accounts only
        {
            "user_id": user_object_id,
            "status": AccountStatus.ACTIVE
        },
        # Try with user_id as string, active accounts only
        {
            "user_id": str(user_object_id) if isinstance(user_object_id, ObjectId) else user_object_id,
            "status": AccountStatus.ACTIVE
        },
        # Also include ERROR status accounts to fix them
        {
            "user_id": user_object_id,
            "status": {"$in": [AccountStatus.ACTIVE, AccountStatus.ERROR]}
        },
        # Try also with string user_id for all statuses except deleted/disconnected
        {
            "user_id": str(user_object_id) if isinstance(user_object_id, ObjectId) else user_object_id,
            "status": {"$nin": [AccountStatus.DISCONNECTED, AccountStatus.DELETED]}
        }
    ]
    
    # Try each query until we find accounts
    accounts = []
    for query in account_queries:
        try:
            accounts = await accounts_collection.find(query).to_list(length=100)
            if accounts:
                break
        except Exception as e:
            logger.error(f"Error querying accounts with {query}: {str(e)}")
    
    if not accounts:
        logger.info(f"No accounts to refresh for user {user_id}")
        return {
            "status": "success",
            "message": "No accounts to refresh",
            "accounts_updated": 0,
            "accounts_failed": 0
        }
    
    # Refresh each account
    success_count = 0
    error_count = 0
    
    for account in accounts:
        account_id = str(account["_id"])
        try:
            # Update balance and transactions for active accounts
            if account.get("status") != AccountStatus.DISCONNECTED:
                await update_account_balance(account_id)
                await fetch_account_transactions(account_id)
                
                # Set account back to active status if it was in error
                if account.get("status") == AccountStatus.ERROR:
                    await accounts_collection.update_one(
                        {"_id": account["_id"]},
                        {"$set": {
                            "status": AccountStatus.ACTIVE,
                            "refresh_error": None,
                            "last_refresh_attempt": get_current_time_ist(),
                            "refresh_status": "success"
                        }}
                    )
                success_count += 1
        except Exception as e:
            logger.error(f"Error refreshing account {account_id}: {str(e)}")
            error_count += 1
            # Don't update to error status anymore
            try:
                await accounts_collection.update_one(
                    {"_id": account["_id"]},
                    {"$set": {
                        "refresh_error": str(e),
                        "last_refresh_attempt": get_current_time_ist(),
                        "refresh_status": "failed"
                    }}
                )
            except Exception as update_err:
                logger.error(f"Error updating account status: {str(update_err)}")
    
    logger.info(f"Refreshed {success_count} accounts for user {user_id}, {error_count} errors")
    
    return {
        "status": "success",
        "accounts_updated": success_count,
        "accounts_failed": error_count
    }

def map_mock_category(mock_category: str) -> TransactionCategory:
    """Map mock category to internal transaction category"""
    category_mapping = {
        "FOOD_AND_DRINK": TransactionCategory.FOOD_DINING,
        "GROCERIES": TransactionCategory.GROCERIES,
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
        "CHARITABLE_GIVING": TransactionCategory.DONATION,
        "SHOPPING": TransactionCategory.SHOPPING,
        "INVESTMENTS": TransactionCategory.INVESTMENTS
    }
    
    return category_mapping.get(mock_category, TransactionCategory.UNKNOWN)