from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from bson import ObjectId
import numpy as np
from scipy import stats
import pandas as pd
import logging

from app.config.database import get_collection
from app.core.exceptions import NotFoundException, BadRequestException
from app.utils.helpers import get_current_time_ist, get_indian_timezone

# Configure logger
logger = logging.getLogger(__name__)

async def categorize_spending(user_id: str, start_date: Optional[datetime] = None, 
                             end_date: Optional[datetime] = None) -> Dict[str, Any]:
    """
    Categorize user's spending patterns and return breakdown by category
    
    Args:
        user_id: User ID
        start_date: Optional start date for analysis
        end_date: Optional end date for analysis
        
    Returns:
        Categorized spending data with percentages and trends
    """
    try:
        # Set default dates if not provided
        if end_date is None:
            end_date = get_current_time_ist()
        
        if start_date is None:
            start_date = end_date - timedelta(days=30)  # Default to last 30 days
            
        # Get transactions from database
        transactions_collection = await get_collection("transactions")
        transactions = await transactions_collection.find({
            "user_id": user_id,
            "transaction_type": "debit",  # Only consider expenses
            "date": {"$gte": start_date, "$lte": end_date}
        }).to_list(length=1000)
        
        if not transactions:
            return {
                "total_spending": 0,
                "categories": {},
                "timeframe": {
                    "start_date": start_date,
                    "end_date": end_date
                }
            }
        
        # Group by category
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
                "description": txn["description"]
            })
        
        # Calculate total spending
        total_spending = sum(cat["total"] for cat in categories.values())
        
        # Calculate percentages and sort
        for cat_name, cat_data in categories.items():
            cat_data["percentage"] = (cat_data["total"] / total_spending * 100) if total_spending > 0 else 0
            cat_data["average_transaction"] = cat_data["total"] / cat_data["count"] if cat_data["count"] > 0 else 0
        
        # Sort categories by total amount spent
        sorted_categories = {k: categories[k] for k in sorted(
            categories.keys(), 
            key=lambda x: categories[x]["total"], 
            reverse=True
        )}
        
        return {
            "total_spending": total_spending,
            "categories": sorted_categories,
            "timeframe": {
                "start_date": start_date,
                "end_date": end_date
            }
        }
    
    except Exception as e:
        logger.error(f"Error in categorize_spending: {str(e)}")
        raise BadRequestException(detail=f"Failed to categorize spending: {str(e)}")

async def analyze_trends(user_id: str, time_period: str = "monthly", 
                        months: int = 6) -> Dict[str, Any]:
    """
    Analyze financial trends over time
    
    Args:
        user_id: User ID
        time_period: 'weekly', 'monthly', or 'quarterly'
        months: Number of months of history to analyze
        
    Returns:
        Trend analysis including income, spending, and savings rate
    """
    try:
        # Calculate date range
        end_date = get_current_time_ist()
        start_date = end_date - timedelta(days=30 * months)
        
        # Get transactions for period
        transactions_collection = await get_collection("transactions")
        transactions = await transactions_collection.find({
            "user_id": user_id,
            "date": {"$gte": start_date, "$lte": end_date}
        }).to_list(length=10000)
        
        if not transactions:
            return {
                "periods": [],
                "income_trend": [],
                "expense_trend": [],
                "savings_trend": [],
                "net_worth_trend": []
            }
        
        # Prepare data structure based on time_period
        period_dict = {}
        
        # Function to get period key from date
        def get_period_key(date):
            if time_period == "weekly":
                # Get the Monday of the week
                return (date - timedelta(days=date.weekday())).strftime("%Y-%m-%d")
            elif time_period == "monthly":
                return date.strftime("%Y-%m")
            else:  # quarterly
                quarter = (date.month - 1) // 3 + 1
                return f"{date.year}-Q{quarter}"
        
        # Categorize transactions by period
        for txn in transactions:
            txn_date = txn["date"]
            period = get_period_key(txn_date)
            
            if period not in period_dict:
                period_dict[period] = {
                    "income": 0,
                    "expenses": 0,
                    "transactions": []
                }
            
            if txn["transaction_type"] == "credit":
                period_dict[period]["income"] += txn["amount"]
            else:  # debit
                period_dict[period]["expenses"] += txn["amount"]
                
            period_dict[period]["transactions"].append(txn)
        
        # Calculate derived metrics
        periods = []
        income_trend = []
        expense_trend = []
        savings_trend = []
        savings_rate_trend = []
        
        # Sort periods chronologically
        sorted_periods = sorted(period_dict.keys())
        
        cumulative_savings = 0
        for period in sorted_periods:
            period_data = period_dict[period]
            income = period_data["income"]
            expenses = period_data["expenses"]
            net_savings = income - expenses
            savings_rate = (net_savings / income * 100) if income > 0 else 0
            cumulative_savings += net_savings
            
            periods.append(period)
            income_trend.append(income)
            expense_trend.append(expenses)
            savings_trend.append(net_savings)
            savings_rate_trend.append(savings_rate)
        
        # Calculate moving averages for smoother trends
        def calculate_moving_average(data, window=3):
            if len(data) < window:
                return data
            return [sum(data[max(0, i-window+1):i+1])/min(window, i+1) for i in range(len(data))]
        
        income_ma = calculate_moving_average(income_trend)
        expense_ma = calculate_moving_average(expense_trend)
        
        # Calculate trend directions (increasing/decreasing)
        income_trend_direction = "increasing" if len(income_trend) > 1 and income_trend[-1] > income_trend[0] else "decreasing"
        expense_trend_direction = "increasing" if len(expense_trend) > 1 and expense_trend[-1] > expense_trend[0] else "decreasing"
        savings_trend_direction = "increasing" if len(savings_trend) > 1 and savings_trend[-1] > savings_trend[0] else "decreasing"
        
        return {
            "periods": periods,
            "income": {
                "values": income_trend,
                "moving_average": income_ma,
                "trend": income_trend_direction,
                "total": sum(income_trend)
            },
            "expenses": {
                "values": expense_trend,
                "moving_average": expense_ma,
                "trend": expense_trend_direction,
                "total": sum(expense_trend)
            },
            "savings": {
                "values": savings_trend,
                "trend": savings_trend_direction,
                "total": sum(savings_trend),
                "cumulative": cumulative_savings
            },
            "savings_rate": {
                "values": savings_rate_trend,
                "average": sum(savings_rate_trend) / len(savings_rate_trend) if savings_rate_trend else 0
            },
            "timeframe": {
                "start_date": start_date,
                "end_date": end_date,
                "period_type": time_period
            }
        }
    
    except Exception as e:
        logger.error(f"Error in analyze_trends: {str(e)}")
        raise BadRequestException(detail=f"Failed to analyze trends: {str(e)}")

async def compare_budget_actual(user_id: str, month: Optional[str] = None) -> Dict[str, Any]:
    """
    Compare budget to actual spending by category
    
    Args:
        user_id: User ID
        month: Optional month in YYYY-MM format (defaults to current month)
        
    Returns:
        Budget vs actual comparison with variances
    """
    try:
        # Set default month to current month if not specified
        current_time = get_current_time_ist()
        ist = get_indian_timezone()
        if not month:
            month = current_time.strftime("%Y-%m")
        
        # Parse month string to get start and end date
        year, month_num = map(int, month.split('-'))
        # Make start_date and end_date timezone-aware
        start_date = ist.localize(datetime(year, month_num, 1))
        if month_num == 12:
            end_date = ist.localize(datetime(year + 1, 1, 1)) - timedelta(seconds=1)
        else:
            end_date = ist.localize(datetime(year, month_num + 1, 1)) - timedelta(seconds=1)
        
        # Get budget from database
        budgets_collection = await get_collection("budgets")
        budget = await budgets_collection.find_one({
            "user_id": user_id,
            "month": month
        })
        
        # If no budget exists for this month, check for default budget
        if not budget:
            budget = await budgets_collection.find_one({
                "user_id": user_id,
                "is_default": True
            })
        
        # Get actual transactions for the month
        transactions_collection = await get_collection("transactions")
        transactions = await transactions_collection.find({
            "user_id": user_id,
            "transaction_type": "debit",
            "date": {"$gte": start_date, "$lt": end_date}
        }).to_list(length=1000)
        
        # Calculate actual spending by category
        actual_by_category = {}
        for txn in transactions:
            category = txn.get("category", "other")
            if category not in actual_by_category:
                actual_by_category[category] = 0
            actual_by_category[category] += txn["amount"]
        
        # Get budget categories
        if budget:
            budget_categories = budget.get("categories", {})
        else:
            budget_categories = {}
        
        # Calculate total budget and actual
        total_budget = sum(budget_categories.values())
        total_actual = sum(actual_by_category.values())
        
        # Calculate variance and performance for each category
        comparison = {}
        all_categories = set(list(budget_categories.keys()) + list(actual_by_category.keys()))
        
        for category in all_categories:
            budget_amount = budget_categories.get(category, 0)
            actual_amount = actual_by_category.get(category, 0)
            variance = budget_amount - actual_amount
            performance = 0 if budget_amount == 0 else (variance / budget_amount) * 100
            
            comparison[category] = {
                "budget": budget_amount,
                "actual": actual_amount,
                "variance": variance,
                "variance_percentage": performance,
                "status": "under_budget" if variance >= 0 else "over_budget"
            }
        
        # Calculate overall metrics
        overall_variance = total_budget - total_actual
        overall_performance = 0 if total_budget == 0 else (overall_variance / total_budget) * 100
        
        return {
            "month": month,
            "total_budget": total_budget,
            "total_actual": total_actual,
            "overall_variance": overall_variance,
            "overall_performance": overall_performance,
            "overall_status": "under_budget" if overall_variance >= 0 else "over_budget",
            "categories": comparison,
            "budget_exists": budget is not None,
            "days_in_month": (end_date - start_date).days + 1,
            "days_elapsed": min((current_time - start_date).days + 1, (end_date - start_date).days + 1)
        }
    
    except Exception as e:
        logger.error(f"Error in compare_budget_actual: {str(e)}")
        raise BadRequestException(detail=f"Failed to compare budget vs actual: {str(e)}")

async def calculate_financial_health_score(user_id: str) -> Dict[str, Any]:
    """
    Calculate overall financial health score based on multiple factors
    
    Args:
        user_id: User ID
        
    Returns:
        Financial health score and breakdown of contributing factors
    """
    try:
        # Get user data
        users_collection = await get_collection("users")
        user = await users_collection.find_one({"_id": ObjectId(user_id)})
        
        if not user:
            raise NotFoundException(detail="User not found")
        
        # Initialize score components (each out of 100)
        score_components = {
            "savings_rate": 0,       # Weight: 25%
            "debt_ratio": 0,         # Weight: 20%
            "emergency_fund": 0,     # Weight: 20%
            "investment_ratio": 0,   # Weight: 15%
            "budget_adherence": 0,   # Weight: 10%
            "income_stability": 0    # Weight: 10%
        }
        
        component_weights = {
            "savings_rate": 0.25,
            "debt_ratio": 0.20,
            "emergency_fund": 0.20,
            "investment_ratio": 0.15,
            "budget_adherence": 0.10,
            "income_stability": 0.10
        }
        
        # Get financial data for the last 3 months
        end_date = get_current_time_ist()
        start_date = end_date - timedelta(days=90)
        
        # Get transactions
        transactions_collection = await get_collection("transactions")
        transactions = await transactions_collection.find({
            "user_id": user_id,
            "date": {"$gte": start_date, "$lte": end_date}
        }).to_list(length=5000)
        
        # Get accounts
        accounts_collection = await get_collection("accounts")
        accounts = await accounts_collection.find({
            "user_id": user_id,
            "status": "active"
        }).to_list(length=100)
        
        # Get portfolios
        portfolios_collection = await get_collection("portfolios")
        portfolios = await portfolios_collection.find({
            "user_id": user_id,
            "is_active": True
        }).to_list(length=20)
        
        # Calculate income and expenses for savings rate
        income = sum(t["amount"] for t in transactions if t["transaction_type"] == "credit")
        expenses = sum(t["amount"] for t in transactions if t["transaction_type"] == "debit")
        
        # 1. Calculate Savings Rate Score
        if income > 0:
            savings_rate = (income - expenses) / income
            # Score increases with savings rate: 0% = 0 points, 20%+ = 100 points
            score_components["savings_rate"] = min(100, 500 * savings_rate)
        
        # 2. Calculate Debt Ratio Score
        total_assets = 0
        total_debt = 0
        
        for account in accounts:
            if account["account_type"] in ["loan", "credit_card"]:
                total_debt += account.get("current_balance", 0)
            else:
                total_assets += account.get("current_balance", 0)
        
        # Add investment assets
        for portfolio in portfolios:
            total_assets += portfolio.get("performance", {}).get("current_value", 0)
        
        # Debt-to-asset ratio (lower is better)
        if total_assets > 0:
            debt_ratio = total_debt / total_assets
            # Score decreases with debt ratio: 0% = 100 points, 100%+ = 0 points
            score_components["debt_ratio"] = max(0, 100 - 100 * debt_ratio)
        elif total_debt == 0:
            # No assets but also no debt is neutral
            score_components["debt_ratio"] = 50
        else:
            # No assets but has debt is bad
            score_components["debt_ratio"] = 0
        
        # 3. Calculate Emergency Fund Score
        monthly_expenses = expenses / 3  # Average monthly expenses
        
        # Get liquid assets (savings and checking accounts)
        emergency_fund = sum(
            account.get("current_balance", 0) for account in accounts 
            if account["account_type"] in ["savings", "current"]
        )
        
        if monthly_expenses > 0:
            months_coverage = emergency_fund / monthly_expenses
            # Score based on months of coverage: 0 = 0 points, 6+ months = 100 points
            score_components["emergency_fund"] = min(100, months_coverage * 100 / 6)
        elif emergency_fund > 0:
            # Has emergency fund but can't calculate months (no expenses)
            score_components["emergency_fund"] = 70
        
        # 4. Calculate Investment Ratio Score
        total_investment = sum(
            portfolio.get("performance", {}).get("current_value", 0) 
            for portfolio in portfolios
        )
        
        if total_assets > 0:
            investment_ratio = total_investment / total_assets
            # Score increases with investment ratio: 0% = 0 points, 30%+ = 100 points
            score_components["investment_ratio"] = min(100, investment_ratio * 100 / 0.3)
        
        # 5. Calculate Budget Adherence Score
        # Get budget vs actual data for the last month
        current_month = end_date.strftime("%Y-%m")
        budget_comparison = await compare_budget_actual(user_id, current_month)
        
        if budget_comparison["budget_exists"]:
            # Better score if under budget, worse if over budget
            if budget_comparison["overall_variance"] >= 0:
                # Under budget is good
                score_components["budget_adherence"] = 100
            else:
                # Over budget: 10% over = 50 points, 20%+ over = 0 points
                variance_pct = abs(budget_comparison["overall_performance"])
                score_components["budget_adherence"] = max(0, 100 - 5 * variance_pct)
        else:
            # No budget exists, neutral score
            score_components["budget_adherence"] = 50
        
        # 6. Calculate Income Stability Score
        if len(transactions) > 0:
            # Group income transactions by month
            monthly_income = {}
            for txn in transactions:
                if txn["transaction_type"] == "credit":
                    month_key = txn["date"].strftime("%Y-%m")
                    if month_key not in monthly_income:
                        monthly_income[month_key] = 0
                    monthly_income[month_key] += txn["amount"]
            
            if len(monthly_income) > 1:
                # Calculate coefficient of variation (lower is more stable)
                income_values = list(monthly_income.values())
                cv = np.std(income_values) / np.mean(income_values) if np.mean(income_values) > 0 else float('inf')
                
                # Score decreases with CV: 0 = 100 points (perfectly stable), 1+ = 0 points (highly variable)
                score_components["income_stability"] = max(0, 100 - 100 * cv)
            else:
                # Only one month of data, neutral score
                score_components["income_stability"] = 50
        
        # Calculate weighted total score
        total_score = sum(
            score * component_weights[component] for component, score in score_components.items()
        )
        
        # Determine score category
        score_category = "excellent"
        if total_score < 30:
            score_category = "critical"
        elif total_score < 50:
            score_category = "poor"
        elif total_score < 70:
            score_category = "fair"
        elif total_score < 85:
            score_category = "good"
        
        # Generate recommendations based on weakest areas
        recommendations = []
        sorted_components = sorted(
            score_components.items(),
            key=lambda x: x[1]
        )
        
        # Generate recommendations for the lowest 2-3 scoring areas
        for component, score in sorted_components[:3]:
            if score < 60:
                if component == "savings_rate":
                    recommendations.append("Increase your savings rate by reducing non-essential expenses")
                elif component == "debt_ratio":
                    recommendations.append("Focus on reducing high-interest debt")
                elif component == "emergency_fund":
                    recommendations.append("Build up your emergency fund to cover 3-6 months of expenses")
                elif component == "investment_ratio":
                    recommendations.append("Increase your regular investments for long-term wealth building")
                elif component == "budget_adherence":
                    recommendations.append("Stick more closely to your monthly budget")
                elif component == "income_stability":
                    recommendations.append("Consider ways to diversify or stabilize your income sources")
        
        return {
            "score": round(total_score, 1),
            "category": score_category,
            "components": {
                component: round(score, 1) for component, score in score_components.items()
            },
            "recommendations": recommendations,
            "analysis_date": end_date,
            "data_period": {
                "start_date": start_date,
                "end_date": end_date
            }
        }
    
    except Exception as e:
        logger.error(f"Error in calculate_financial_health_score: {str(e)}")
        if isinstance(e, NotFoundException):
            raise
        raise BadRequestException(detail=f"Failed to calculate financial health score: {str(e)}")