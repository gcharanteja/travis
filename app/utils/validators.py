import re
import datetime
from typing import Optional, Union, Dict, Any
from dateutil.parser import parse
import phonenumbers

class ValidationError(Exception):
    """Custom exception for validation errors"""
    pass

# Financial data validators
def validate_pan_card(pan_number: str) -> bool:
    """
    Validate Indian PAN (Permanent Account Number) card format
    Format: AAAAA1234A (5 letters, 4 numbers, 1 letter)
    """
    if not pan_number:
        return False
    
    pattern = r'^[A-Z]{5}[0-9]{4}[A-Z]{1}$'
    return bool(re.match(pattern, pan_number))

def validate_aadhaar(aadhaar_number: str) -> bool:
    """
    Validate Indian Aadhaar number format (12 digits)
    """
    if not aadhaar_number:
        return False
    
    # Remove spaces if any
    aadhaar_number = aadhaar_number.replace(" ", "")
    pattern = r'^\d{12}$'
    return bool(re.match(pattern, aadhaar_number))

def validate_ifsc_code(ifsc_code: str) -> bool:
    """
    Validate IFSC (Indian Financial System Code) format
    Format: AAAA0123456 (4 letters representing bank, 0, 6 alphanumeric for branch)
    """
    if not ifsc_code:
        return False
    
    pattern = r'^[A-Z]{4}0[A-Z0-9]{6}$'
    return bool(re.match(pattern, ifsc_code))

def validate_account_number(account_number: str) -> bool:
    """
    Validate bank account number (numeric only, between 9-18 digits)
    """
    if not account_number:
        return False
    
    pattern = r'^\d{9,18}$'
    return bool(re.match(pattern, account_number))

def validate_upi_id(upi_id: str) -> bool:
    """
    Validate UPI ID format (typically username@provider)
    """
    if not upi_id:
        return False
    
    pattern = r'^[\w\.\-]+@[\w\-]+$'
    return bool(re.match(pattern, upi_id))

# Contact information validators
def validate_indian_phone(phone_number: str) -> bool:
    """
    Validate Indian phone number format using phonenumbers library
    """
    if not phone_number:
        return False
    
    # Add India country code if not present
    if not phone_number.startswith('+'):
        phone_number = '+91' + phone_number.lstrip('0')
        
    try:
        parsed_number = phonenumbers.parse(phone_number, "IN")
        return phonenumbers.is_valid_number(parsed_number)
    except:
        return False

def validate_email(email: str) -> bool:
    """
    Validate email address format
    """
    if not email:
        return False
    
    pattern = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'
    return bool(re.match(pattern, email))

def validate_pincode(pincode: str) -> bool:
    """
    Validate Indian PIN code (postal code) - 6 digits
    """
    if not pincode:
        return False
    
    pattern = r'^\d{6}$'
    return bool(re.match(pattern, pincode))

# Financial goal validators
def validate_financial_goal(goal_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate financial goal data structure
    """
    errors = {}
    
    # Required fields
    required_fields = ['name', 'target_amount', 'target_date']
    for field in required_fields:
        if field not in goal_data or not goal_data[field]:
            errors[field] = f"{field} is required"
    
    # Amount validation
    if 'target_amount' in goal_data:
        try:
            amount = float(goal_data['target_amount'])
            if amount <= 0:
                errors['target_amount'] = "Target amount must be positive"
        except ValueError:
            errors['target_amount'] = "Target amount must be a number"
    
    # Date validation
    if 'target_date' in goal_data and goal_data['target_date']:
        try:
            target_date = parse(goal_data['target_date']).date()
            today = datetime.date.today()
            if target_date <= today:
                errors['target_date'] = "Target date must be in the future"
        except ValueError:
            errors['target_date'] = "Invalid date format"
    
    # Category validation
    valid_categories = [
        'retirement', 'education', 'home', 'vehicle', 'travel', 
        'wedding', 'emergency_fund', 'debt_payoff', 'other'
    ]
    if 'category' in goal_data and goal_data['category']:
        if goal_data['category'] not in valid_categories:
            errors['category'] = f"Category must be one of: {', '.join(valid_categories)}"
    
    return errors

def validate_password_strength(password: str) -> Dict[str, Union[bool, str]]:
    """
    Validate password strength with specific requirements
    """
    result = {
        'valid': False,
        'message': ""
    }
    
    if len(password) < 8:
        result['message'] = "Password must be at least 8 characters long"
        return result
    
    if not re.search(r'[A-Z]', password):
        result['message'] = "Password must include at least one uppercase letter"
        return result
    
    if not re.search(r'[a-z]', password):
        result['message'] = "Password must include at least one lowercase letter"
        return result
    
    if not re.search(r'[0-9]', password):
        result['message'] = "Password must include at least one number"
        return result
    
    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        result['message'] = "Password must include at least one special character"
        return result
    
    result['valid'] = True
    result['message'] = "Password meets all requirements"
    return result

def validate_date_format(date_str: str, format_str: str = "%Y-%m-%d") -> bool:
    """
    Validate if a string matches the given date format
    """
    try:
        datetime.datetime.strptime(date_str, format_str)
        return True
    except ValueError:
        return False

def validate_investment_amount(amount: Union[str, float, int]) -> bool:
    """
    Validate investment amount (must be positive and within reasonable range)
    """
    try:
        amount_float = float(amount)
        # Amount must be positive and less than 10 crore (reasonable upper limit)
        return 0 < amount_float <= 100000000
    except (ValueError, TypeError):
        return False

def sanitize_input(input_str: str) -> str:
    """
    Sanitize input string to prevent injection attacks
    """
    # Remove HTML tags
    clean_text = re.sub(r'<[^>]*>', '', input_str)
    # Remove potentially dangerous characters
    clean_text = re.sub(r'[;\'"]', '', clean_text)
    return clean_text