import logging
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Union, Tuple
import numpy as np
import pandas as pd
from scipy import stats
from bson import ObjectId
import uuid

from app.config.settings import get_settings
from app.config.database import get_collection
from app.core.exceptions import (
    NotFoundException, 
    InvestmentException,
    BadRequestException
)
from app.models.portfolio import (
    Portfolio, 
    InvestmentHolding,
    AssetClass,
    InvestmentType,
    RiskProfile,
    PortfolioPerformance,
    AssetAllocation
)
from app.utils.helpers import get_current_time_ist

# Get settings
settings = get_settings()

# Configure logger
logger = logging.getLogger(__name__)

async def create_portfolio(user_id: str, portfolio_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create a new investment portfolio
    
    Args:
        user_id: User ID
        portfolio_data: Portfolio creation data
        
    Returns:
        Created portfolio
    """
    try:
        # Verify user exists
        users_collection = await get_collection("users")
        
        # Try different user_id formats
        user = None
        
        # Try with string ID first
        user = await users_collection.find_one({"_id": user_id})
        
        # If not found, try with ObjectId
        if not user:
            try:
                object_id = ObjectId(user_id)
                user = await users_collection.find_one({"_id": object_id})
            except Exception as e:
                logger.debug(f"Failed to convert user_id to ObjectId: {str(e)}")
        
        # Still not found? Try with string ID in 'id' field
        if not user:
            user = await users_collection.find_one({"id": user_id})
            
        if not user:
            raise NotFoundException(detail="User not found")
        
        # Check portfolio name uniqueness for the user
        portfolios_collection = await get_collection("portfolios")
        existing = await portfolios_collection.find_one({
            "user_id": user_id,
            "name": portfolio_data["name"]
        })
        if existing:
            raise BadRequestException(
                detail="Portfolio with this name already exists",
                code="duplicate_portfolio"
            )
        
        # Create portfolio
        current_time = get_current_time_ist()
        portfolio = Portfolio(
            user_id=user_id,
            name=portfolio_data["name"],
            description=portfolio_data.get("description"),
            portfolio_type=portfolio_data.get("portfolio_type", "custom"),
            risk_profile=portfolio_data.get("risk_profile", RiskProfile.MODERATE),
            is_default=portfolio_data.get("is_default", False),
            is_auto_rebalance=portfolio_data.get("is_auto_rebalance", False),
            rebalance_frequency=portfolio_data.get("rebalance_frequency"),
            goal_ids=portfolio_data.get("goal_ids", []),
            created_at=current_time,
            updated_at=current_time
        )
        
        # If this is the default portfolio, unset default on others
        if portfolio.is_default:
            await portfolios_collection.update_many(
                {"user_id": user_id, "is_default": True},
                {"$set": {"is_default": False}}
            )
        
        # Set asset allocation if provided
        if "target_allocation" in portfolio_data:
            target_allocation = portfolio_data["target_allocation"]
            portfolio.asset_allocation.target_allocation = target_allocation
            
            # Initialize current allocation to target (will be updated with holdings)
            portfolio.asset_allocation.current_allocation = target_allocation.copy()
            
            # Set asset class percentages
            for asset_class, percentage in target_allocation.items():
                if asset_class == "equity":
                    portfolio.asset_allocation.equity_percentage = percentage
                elif asset_class == "debt":
                    portfolio.asset_allocation.debt_percentage = percentage
                elif asset_class == "cash":
                    portfolio.asset_allocation.cash_percentage = percentage
                elif asset_class == "real_estate":
                    portfolio.asset_allocation.real_estate_percentage = percentage
                elif asset_class == "gold":
                    portfolio.asset_allocation.gold_percentage = percentage
                elif asset_class == "alternative":
                    portfolio.asset_allocation.alternative_percentage = percentage
                elif asset_class == "crypto":
                    portfolio.asset_allocation.crypto_percentage = percentage
        
        # Save portfolio
        result = await portfolios_collection.insert_one(portfolio.dict())
        
        # Update user's portfolio IDs list
        await users_collection.update_one(
            {"_id": user_id},
            {"$push": {"portfolio_ids": str(result.inserted_id)}}
        )
        
        # If portfolio is linked to goals, update goals
        if portfolio.goal_ids:
            goals_collection = await get_collection("goals")
            for goal_id in portfolio.goal_ids:
                await goals_collection.update_one(
                    {"_id": goal_id},
                    {"$set": {"portfolio_id": str(result.inserted_id)}}
                )
        
        logger.info(f"Created portfolio {result.inserted_id} for user {user_id}")
        
        # Return created portfolio
        created_portfolio = await portfolios_collection.find_one({"_id": result.inserted_id})
        return created_portfolio
    
    except Exception as e:
        if isinstance(e, (NotFoundException, BadRequestException)):
            raise
        logger.error(f"Error creating portfolio: {str(e)}")
        raise InvestmentException(detail=f"Failed to create portfolio: {str(e)}")

async def add_holdings(portfolio_id: str, holdings_data: Union[Dict[str, Any], List[Dict[str, Any]]]) -> Dict[str, Any]:
    """
    Add holdings to a portfolio
    
    Args:
        portfolio_id: Portfolio ID
        holdings_data: Holding data or list of holdings
        
    Returns:
        Updated portfolio
    """
    try:
        # Convert to list if single holding
        if not isinstance(holdings_data, list):
            holdings_data = [holdings_data]
        
        # Get portfolio - try multiple ID formats
        portfolios_collection = await get_collection("portfolios")
        
        # First try as ObjectId
        portfolio = None
        try:
            object_id = ObjectId(portfolio_id)
            portfolio = await portfolios_collection.find_one({"_id": object_id})
        except Exception as e:
            logger.debug(f"Failed to find portfolio with ObjectId: {e}")
        
        # If not found, try with string ID
        if not portfolio:
            portfolio = await portfolios_collection.find_one({"id": portfolio_id})
            
        # Try one more time with transaction_id field
        if not portfolio:
            portfolio = await portfolios_collection.find_one({"transaction_id": portfolio_id})
            
        # If still not found, try with the _id field as string
        if not portfolio:
            portfolio = await portfolios_collection.find_one({"_id": portfolio_id})
        
        if not portfolio:
            logger.error(f"Portfolio not found with ID: {portfolio_id}")
            raise NotFoundException(detail="Portfolio not found")
        
        # Process each holding
        current_time = get_current_time_ist()
        holdings = []
        for holding_data in holdings_data:
            # Create a new holding ID
            holding_id = str(uuid.uuid4())
            
            # Ensure instrument_id is always present
            instrument_id = holding_data.get("instrument_id")
            if not instrument_id:  # This handles None, empty string, etc.
                instrument_id = str(uuid.uuid4())
            
            # Calculate current value and invested amount
            units = float(holding_data["units"])
            current_price = float(holding_data["current_price"])
            avg_price = float(holding_data["average_buy_price"])
            
            current_value = units * current_price
            invested_amount = units * avg_price
            unrealized_gain_loss = current_value - invested_amount
            unrealized_pct = (unrealized_gain_loss / invested_amount * 100) if invested_amount > 0 else 0
            
            # Create holding object
            holding = {
                "id": holding_id,
                "instrument_id": instrument_id,  # Now guaranteed to be a valid string
                "instrument_name": holding_data["instrument_name"],
                "instrument_type": holding_data["instrument_type"],
                "units": units,
                "average_buy_price": avg_price,
                "current_price": current_price,
                "current_value": current_value,
                "invested_amount": invested_amount,
                "asset_class": holding_data["asset_class"],
                "sector": holding_data.get("sector"),
                "industry": holding_data.get("industry"),
                "unrealized_gain_loss": unrealized_gain_loss,
                "unrealized_gain_loss_percentage": unrealized_pct,
                "dividend_income": 0.0,  # Default value to avoid null
                "last_price_update": current_time,
                "created_at": current_time,
                "updated_at": current_time
            }
            
            # Add optional fields
            if "nav" in holding_data:
                holding["nav"] = holding_data["nav"]
            if "scheme_code" in holding_data:
                holding["scheme_code"] = holding_data["scheme_code"]
            if "folio_number" in holding_data:
                holding["folio_number"] = holding_data["folio_number"]
            if "exchange" in holding_data:
                holding["exchange"] = holding_data["exchange"]
            if "ticker" in holding_data:
                holding["ticker"] = holding_data["ticker"]
            if "isin" in holding_data:
                holding["isin"] = holding_data["isin"]
            
            holdings.append(holding)
        
        # Update portfolio with new holdings
        portfolio_holdings = portfolio.get("holdings", [])
        portfolio_holdings.extend(holdings)
        
        # Update performance metrics
        performance = await _calculate_portfolio_performance(portfolio_holdings)
        
        # Update asset allocation
        asset_allocation = await _calculate_asset_allocation(
            portfolio_holdings, 
            portfolio.get("asset_allocation", {}).get("target_allocation", {})
        )
        
        # Check if portfolio needs rebalancing
        needs_rebalance = await _check_rebalance_needed(
            asset_allocation.get("current_allocation", {}),
            asset_allocation.get("target_allocation", {})
        )
        
        # Set needs_rebalance directly in the asset_allocation object
        asset_allocation["needs_rebalance"] = needs_rebalance
        
        # Update portfolio - use the _id we found in our query
        portfolio_id_to_update = portfolio["_id"]
        try:
            await portfolios_collection.update_one(
                {"_id": portfolio_id_to_update},
                {
                    "$set": {
                        "holdings": portfolio_holdings,
                        "performance": performance,
                        "asset_allocation": asset_allocation,
                        "updated_at": current_time
                    }
                }
            )
        except Exception as e:
            logger.error(f"MongoDB update error: {str(e)}", exc_info=True)
            raise InvestmentException(detail=f"Failed to update portfolio in database: {str(e)}")
        
        # Return updated portfolio
        updated_portfolio = await portfolios_collection.find_one({"_id": portfolio_id_to_update})
        if not updated_portfolio:
            logger.error("Failed to retrieve updated portfolio after update")
            raise InvestmentException(detail="Failed to retrieve updated portfolio")
            
        return updated_portfolio
    
    except Exception as e:
        if isinstance(e, NotFoundException):
            raise e
        logger.error(f"Error adding holdings: {str(e)}", exc_info=True)
        raise InvestmentException(detail=f"Failed to add holdings: {str(e)}")

async def update_holding(portfolio_id: str, holding_id: str, update_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Update an investment holding
    
    Args:
        portfolio_id: Portfolio ID
        holding_id: Holding ID
        update_data: Data to update
        
    Returns:
        Updated portfolio
    """
    try:
        # Get portfolio
        portfolios_collection = await get_collection("portfolios")
        portfolio = await portfolios_collection.find_one({"_id": portfolio_id})
        if not portfolio:
            raise NotFoundException(detail="Portfolio not found")
        
        # Find holding to update
        holdings = portfolio.get("holdings", [])
        holding_index = next((i for i, h in enumerate(holdings) if h["id"] == holding_id), None)
        
        if holding_index is None:
            raise NotFoundException(detail="Holding not found")
        
        # Update holding
        current_time = get_current_time_ist()
        holding = holdings[holding_index]
        
        # Apply updates
        for key, value in update_data.items():
            if key in holding:
                holding[key] = value
        
        # Recalculate derived values
        current_value = holding["units"] * holding["current_price"]
        invested_amount = holding["units"] * holding["average_buy_price"]
        unrealized_gain_loss = current_value - invested_amount
        unrealized_gain_loss_percentage = (unrealized_gain_loss / invested_amount) * 100 if invested_amount > 0 else 0
        
        holding["current_value"] = current_value
        holding["invested_amount"] = invested_amount
        holding["unrealized_gain_loss"] = unrealized_gain_loss
        holding["unrealized_gain_loss_percentage"] = unrealized_gain_loss_percentage
        holding["updated_at"] = current_time
        holding["last_price_update"] = current_time
        
        holdings[holding_index] = holding
        
        # Update performance metrics
        performance = await _calculate_portfolio_performance(holdings)
        
        # Update asset allocation
        asset_allocation = await _calculate_asset_allocation(
            holdings, 
            portfolio.get("asset_allocation", {}).get("target_allocation", {})
        )
        
        # Check if portfolio needs rebalancing
        needs_rebalance = await _check_rebalance_needed(
            asset_allocation.get("current_allocation", {}),
            asset_allocation.get("target_allocation", {})
        )
        
        # Update portfolio
        await portfolios_collection.update_one(
            {"_id": portfolio_id},
            {
                "$set": {
                    "holdings": holdings,
                    "performance": performance,
                    "asset_allocation": asset_allocation,
                    "updated_at": current_time,
                    "asset_allocation.needs_rebalance": needs_rebalance
                }
            }
        )
        
        # Return updated portfolio
        updated_portfolio = await portfolios_collection.find_one({"_id": portfolio_id})
        return updated_portfolio
    
    except Exception as e:
        if isinstance(e, NotFoundException):
            raise
        logger.error(f"Error updating holding: {str(e)}")
        raise InvestmentException(detail=f"Failed to update holding: {str(e)}")

async def remove_holding(portfolio_id: str, holding_id: str) -> Dict[str, Any]:
    """
    Remove a holding from a portfolio
    
    Args:
        portfolio_id: Portfolio ID
        holding_id: Holding ID
        
    Returns:
        Updated portfolio
    """
    try:
        # Get portfolio
        portfolios_collection = await get_collection("portfolios")
        portfolio = await portfolios_collection.find_one({"_id": portfolio_id})
        if not portfolio:
            raise NotFoundException(detail="Portfolio not found")
        
        # Remove holding
        holdings = portfolio.get("holdings", [])
        original_length = len(holdings)
        holdings = [h for h in holdings if h["id"] != holding_id]
        
        if len(holdings) == original_length:
            raise NotFoundException(detail="Holding not found")
        
        # Update performance metrics
        current_time = get_current_time_ist()
        performance = await _calculate_portfolio_performance(holdings)
        
        # Update asset allocation
        asset_allocation = await _calculate_asset_allocation(
            holdings, 
            portfolio.get("asset_allocation", {}).get("target_allocation", {})
        )
        
        # Check if portfolio needs rebalancing
        needs_rebalance = await _check_rebalance_needed(
            asset_allocation.get("current_allocation", {}),
            asset_allocation.get("target_allocation", {})
        )
        
        # Update portfolio
        await portfolios_collection.update_one(
            {"_id": portfolio_id},
            {
                "$set": {
                    "holdings": holdings,
                    "performance": performance,
                    "asset_allocation": asset_allocation,
                    "updated_at": current_time,
                    "asset_allocation.needs_rebalance": needs_rebalance
                }
            }
        )
        
        # Return updated portfolio
        updated_portfolio = await portfolios_collection.find_one({"_id": portfolio_id})
        return updated_portfolio
    
    except Exception as e:
        if isinstance(e, NotFoundException):
            raise
        logger.error(f"Error removing holding: {str(e)}")
        raise InvestmentException(detail=f"Failed to remove holding: {str(e)}")

async def get_portfolio_details(portfolio_id: str) -> Dict[str, Any]:
    """
    Get detailed information about a portfolio
    
    Args:
        portfolio_id: Portfolio ID
        
    Returns:
        Portfolio details
    """
    try:
        # Get portfolio - try multiple ID formats
        portfolios_collection = await get_collection("portfolios")
        
        # First try as ObjectId
        portfolio = None
        try:
            object_id = ObjectId(portfolio_id)
            portfolio = await portfolios_collection.find_one({"_id": object_id})
        except Exception as e:
            logger.debug(f"Failed to find portfolio with ObjectId: {e}")
        
        # If not found, try with string ID
        if not portfolio:
            portfolio = await portfolios_collection.find_one({"id": portfolio_id})
            
        # Try one more time with transaction_id field
        if not portfolio:
            portfolio = await portfolios_collection.find_one({"transaction_id": portfolio_id})
            
        # If still not found, try with the _id field as string
        if not portfolio:
            portfolio = await portfolios_collection.find_one({"_id": portfolio_id})
        
        if not portfolio:
            raise NotFoundException(detail="Portfolio not found form get portfolio details")

        # Enrich portfolio with additional details
        enriched_portfolio = await _enrich_portfolio_details(portfolio)
        
        return enriched_portfolio
    
    except Exception as e:
        if isinstance(e, NotFoundException):
            raise
        logger.error(f"Error fetching portfolio details: {str(e)}")
        raise InvestmentException(detail=f"Failed to fetch portfolio details: {str(e)}")

async def _calculate_portfolio_performance(holdings: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Calculate overall portfolio performance based on holdings
    """
    try:
        current_time = get_current_time_ist()
        
        # Initialize performance metrics
        total_invested = sum(holding.get("invested_amount", 0) for holding in holdings)
        total_current_value = sum(holding.get("current_value", 0) for holding in holdings)
        
        total_return = total_current_value - total_invested
        return_percentage = (total_return / total_invested * 100) if total_invested > 0 else 0
        
        # Calculate performance by asset class
        asset_class_performance = {}
        for asset_class in {holding.get("asset_class") for holding in holdings if holding.get("asset_class")}:
            class_holdings = [h for h in holdings if h.get("asset_class") == asset_class]
            class_invested = sum(holding.get("invested_amount", 0) for holding in class_holdings)
            class_current = sum(holding.get("current_value", 0) for holding in class_holdings)
            class_return = class_current - class_invested
            class_return_pct = (class_return / class_invested * 100) if class_invested > 0 else 0
            
            asset_class_performance[asset_class] = {
                "invested_amount": class_invested,
                "current_value": class_current,
                "return": class_return,
                "return_percentage": class_return_pct
            }
        
        # Construct performance object with all required fields
        performance = {
            "current_value": total_current_value,
            "invested_value": total_invested,
            "total_gain_loss": total_return,
            "total_gain_loss_percentage": return_percentage,
            "one_day_return": None,
            "one_month_return": None, 
            "three_month_return": None,
            "six_month_return": None,
            "ytd_return": None,
            "one_year_return": None,
            "since_inception_return": None,
            "volatility": None,
            "sharpe_ratio": None,
            "last_updated": current_time  # Ensure this field is always present
        }
        
        return performance
    except Exception as e:
        logger.error(f"Error calculating portfolio performance: {str(e)}")
        # Return default performance with last_updated to avoid validation errors
        return {
            "current_value": 0.0,
            "invested_value": 0.0,
            "total_gain_loss": 0.0,
            "total_gain_loss_percentage": 0.0,
            "one_day_return": None,
            "one_month_return": None,
            "three_month_return": None,
            "six_month_return": None,
            "ytd_return": None,
            "one_year_return": None,
            "since_inception_return": None,
            "volatility": None,
            "sharpe_ratio": None,
            "last_updated": get_current_time_ist()  # Always provide this even in error case
        }

async def _calculate_asset_allocation(holdings: List[Dict[str, Any]], target_allocation: Dict[str, float]) -> Dict[str, Any]:
    """
    Calculate current asset allocation and compare with target allocation
    
    Args:
        holdings: List of holdings
        target_allocation: Target allocation percentages
        
    Returns:
        Asset allocation details
    """
    try:
        # Total values by asset class
        total_values = {}
        for holding in holdings:
            asset_class = holding["asset_class"]
            current_value = holding["current_value"]
            if asset_class not in total_values:
                total_values[asset_class] = 0
            total_values[asset_class] += current_value
        
        # Calculate current allocation percentages
        current_allocation = {k: 0 for k in target_allocation.keys()}
        for asset_class, total_value in total_values.items():
            if asset_class in target_allocation:
                current_allocation[asset_class] = total_value
        
        # Check for rebalancing need
        needs_rebalance = False
        for asset_class, target_percentage in target_allocation.items():
            target_value = sum(holding["invested_amount"] for holding in holdings if holding["asset_class"] == asset_class)
            current_value = current_allocation[asset_class]
            # Rebalance if current value is significantly different from target value
            if target_value > 0:
                deviation = abs(current_value - target_value)
                if deviation / target_value > 0.05:  # 5% deviation
                    needs_rebalance = True
                    break
        
        # Asset allocation details
        asset_allocation_details = {
            "target_allocation": target_allocation,
            "current_allocation": current_allocation,
            "needs_rebalance": needs_rebalance
        }
        
        return asset_allocation_details
    
    except Exception as e:
        logger.error(f"Error calculating asset allocation: {str(e)}")
        return {}

async def _check_rebalance_needed(current_allocation: Dict[str, float], target_allocation: Dict[str, float]) -> bool:
    """
    Check if portfolio rebalancing is needed based on current and target allocation
    
    Args:
        current_allocation: Current asset allocation
        target_allocation: Target asset allocation
        
    Returns:
        True if rebalancing is needed, False otherwise
    """
    try:
        for asset_class, target_percentage in target_allocation.items():
            current_percentage = current_allocation.get(asset_class, 0)
            # Rebalance if current percentage is significantly different from target percentage
            if target_percentage > 0:
                deviation = abs(current_percentage - target_percentage)
                if deviation > 5:  # 5% deviation
                    return True
        
        return False
    
    except Exception as e:
        logger.error(f"Error checking rebalancing need: {str(e)}")
        return False

async def _enrich_portfolio_details(portfolio: Dict[str, Any]) -> Dict[str, Any]:
    """
    Enrich portfolio details with additional information
    
    Args:
        portfolio: Portfolio data
        
    Returns:
        Enriched portfolio data
    """
    try:
        # Calculate performance metrics
        performance = await _calculate_portfolio_performance(portfolio.get("holdings", []))
        portfolio["performance"] = performance
        
        # Calculate asset allocation
        asset_allocation = await _calculate_asset_allocation(
            portfolio.get("holdings", []), 
            portfolio.get("asset_allocation", {}).get("target_allocation", {})
        )
        portfolio["asset_allocation"] = asset_allocation
        
        return portfolio
    
    except Exception as e:
        logger.error(f"Error enriching portfolio details: {str(e)}")
        return portfolio