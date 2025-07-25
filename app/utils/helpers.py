import os
import re
import json
import uuid
import base64
import hashlib
import logging
import datetime
from typing import Dict, List, Any, Union, Optional
from dateutil.relativedelta import relativedelta
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
from pathlib import Path
import pytz

# Configure logger
logger = logging.getLogger(__name__)

# Date and time helpers
def get_indian_timezone():
    """Get the Indian Standard Time timezone"""
    return pytz.timezone('Asia/Kolkata')

def get_current_time_ist():
    """Get current time in Indian Standard Time"""
    ist = get_indian_timezone()
    return datetime.datetime.now(ist)

def format_date_indian(date_obj: datetime.date) -> str:
    """Format date in Indian style (DD-MM-YYYY)"""
    if not date_obj:
        return ""
    return date_obj.strftime("%d-%m-%Y")

def parse_date_indian(date_str: str) -> datetime.date:
    """Parse date from Indian format (DD-MM-YYYY)"""
    try:
        return datetime.datetime.strptime(date_str, "%d-%m-%Y").date()
    except ValueError:
        logger.error(f"Failed to parse date: {date_str}")
        raise ValueError(f"Invalid date format: {date_str}. Expected DD-MM-YYYY")

def get_financial_year() -> str:
    """
    Get current Indian financial year (April to March)
    Returns format: "FY 2023-24"
    """
    today = datetime.date.today()
    if today.month < 4:  # Jan to March
        return f"FY {today.year-1}-{str(today.year)[2:]}"
    else:  # April to Dec
        return f"FY {today.year}-{str(today.year+1)[2:]}"

def get_financial_year_dates() -> Dict[str, datetime.date]:
    """
    Get start and end dates for current Indian financial year
    """
    today = datetime.date.today()
    if today.month < 4:  # Jan to March
        start_date = datetime.date(today.year - 1, 4, 1)
        end_date = datetime.date(today.year, 3, 31)
    else:  # April to Dec
        start_date = datetime.date(today.year, 4, 1)
        end_date = datetime.date(today.year + 1, 3, 31)
    
    return {"start_date": start_date, "end_date": end_date}

def age_from_dob(dob: datetime.date) -> int:
    """Calculate age from date of birth"""
    today = datetime.date.today()
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))

# Currency and financial helpers
def format_currency_inr(amount: float) -> str:
    """
    Format amount in Indian currency format (₹)
    Example: ₹1,00,000.00
    """
    if not amount and amount != 0:
        return "₹0.00"
    
    amount_str = f"{abs(amount):,.2f}"
    # Convert to Indian number system (with commas)
    parts = amount_str.split(".")
    integer_part = parts[0].replace(",", "")
    
    # Add commas for Indian numbering system
    result = ""
    if len(integer_part) > 3:
        result = "," + integer_part[-3:]
        integer_part = integer_part[:-3]
        
        while len(integer_part) > 2:
            result = "," + integer_part[-2:] + result
            integer_part = integer_part[:-2]
        
        result = integer_part + result
    else:
        result = integer_part
    
    if len(parts) > 1:
        result = result + "." + parts[1]
    
    # Add negative sign and rupee symbol
    prefix = "-₹" if amount < 0 else "₹"
    return f"{prefix}{result}"

def to_decimal_crores(amount: float) -> str:
    """
    Convert amount to crores with 2 decimal places
    Example: ₹1.25 Cr
    """
    if not amount:
        return "₹0 Cr"
    
    crores = amount / 10000000
    return f"₹{crores:.2f} Cr"

def to_decimal_lakhs(amount: float) -> str:
    """
    Convert amount to lakhs with 2 decimal places
    Example: ₹1.25 L
    """
    if not amount:
        return "₹0 L"
    
    lakhs = amount / 100000
    return f"₹{lakhs:.2f} L"

# Identifier generation
def generate_unique_id(prefix: str = "") -> str:
    """Generate a unique identifier with optional prefix"""
    unique_id = str(uuid.uuid4())
    if prefix:
        return f"{prefix}_{unique_id}"
    return unique_id

def generate_transaction_id() -> str:
    """Generate unique transaction ID"""
    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    random_part = str(uuid.uuid4().hex)[:8]
    return f"TXN_{timestamp}_{random_part}"

# File and data handling
def ensure_directory_exists(directory_path: str) -> bool:
    """Ensure a directory exists, create if it doesn't"""
    if not os.path.exists(directory_path):
        try:
            os.makedirs(directory_path)
            return True
        except Exception as e:
            logger.error(f"Failed to create directory {directory_path}: {e}")
            return False
    return True

def save_json_to_file(data: Dict[str, Any], file_path: str) -> bool:
    """Save dictionary data to JSON file"""
    try:
        directory = os.path.dirname(file_path)
        ensure_directory_exists(directory)
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        return True
    except Exception as e:
        logger.error(f"Failed to save JSON to {file_path}: {e}")
        return False

def load_json_from_file(file_path: str) -> Dict[str, Any]:
    """Load JSON data from file"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load JSON from {file_path}: {e}")
        return {}

# Data visualization helpers
def generate_spending_pie_chart(
    categories: Dict[str, float], 
    title: str = "Monthly Expenditure", 
    output_path: Optional[str] = None
) -> str:
    """
    Generate a pie chart for spending categories
    Returns the path to saved image
    """
    try:
        # Create figure
        plt.figure(figsize=(10, 7))
        plt.pie(
            categories.values(), 
            labels=categories.keys(), 
            autopct='%1.1f%%', 
            startangle=140
        )
        plt.title(title)
        plt.axis('equal')  # Equal aspect ratio ensures the pie chart is circular
        
        # Save if output path provided
        if output_path:
            ensure_directory_exists(os.path.dirname(output_path))
            plt.savefig(output_path, bbox_inches='tight', dpi=300)
            plt.close()
            return output_path
        else:
            # Generate temporary file
            temp_file = f"temp_chart_{uuid.uuid4()}.png"
            plt.savefig(temp_file, bbox_inches='tight', dpi=300)
            plt.close()
            return temp_file
    except Exception as e:
        logger.error(f"Failed to generate pie chart: {e}")
        return ""

def calculate_compound_interest(
    principal: float,
    rate_of_interest: float,  # Annual rate in percentage
    time_years: float,
    frequency: int = 1  # 1=annual, 4=quarterly, 12=monthly
) -> float:
    """
    Calculate compound interest
    Formula: P(1 + r/n)^(nt)
    """
    rate_decimal = rate_of_interest / 100
    return principal * ((1 + (rate_decimal / frequency)) ** (frequency * time_years))

def calculate_sip_returns(
    monthly_investment: float,
    annual_return_rate: float,  # Annual rate in percentage
    time_years: int
) -> Dict[str, float]:
    """
    Calculate returns for Systematic Investment Plan (SIP)
    """
    rate_monthly = (annual_return_rate / 100) / 12
    months = time_years * 12
    
    # Calculate future value of SIP
    amount_invested = monthly_investment * months
    future_value = monthly_investment * (((1 + rate_monthly) ** months - 1) / rate_monthly) * (1 + rate_monthly)
    
    return {
        "amount_invested": amount_invested,
        "estimated_returns": future_value - amount_invested,
        "future_value": future_value
    }

# Security and encryption helpers
def hash_password(password: str, salt: Optional[str] = None) -> Dict[str, str]:
    """
    Generate password hash with salt
    """
    if not salt:
        salt = os.urandom(32).hex()
    
    # Hash password with salt
    key = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        100000  # Number of iterations
    ).hex()
    
    return {'hash': key, 'salt': salt}

def mask_pan(pan_number: str) -> str:
    """Mask PAN card number for display (ABCDE1234F -> ABCDE****F)"""
    if not pan_number or len(pan_number) != 10:
        return pan_number
    return pan_number[:5] + '****' + pan_number[-1]

def mask_aadhaar(aadhaar_number: str) -> str:
    """Mask Aadhaar number for display (123456789012 -> ********9012)"""
    if not aadhaar_number or len(aadhaar_number) != 12:
        return aadhaar_number
    return '*' * 8 + aadhaar_number[-4:]

def mask_account_number(account_number: str) -> str:
    """Mask bank account number for display"""
    if not account_number or len(account_number) < 4:
        return account_number
    return 'X' * (len(account_number) - 4) + account_number[-4:]

def convert_mongo_document(doc):
    """Convert MongoDB document for API response (handles ObjectId and required fields)"""
    if not doc:
        return None

    # Convert _id to string id but keep _id for internal use
    if "_id" in doc:
        doc["id"] = str(doc["_id"])

    # Ensure required fields for transaction responses
    if "transaction_id" not in doc:
        doc["transaction_id"] = str(doc.get("id", doc.get("_id", "")))
    if "original_description" not in doc:
        doc["original_description"] = doc.get("description", "")

    return doc