from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, status, Path, Query
from bson import ObjectId
import logging

from app.config.database import get_collection
from app.core.security import oauth2_scheme, decode_access_token
from app.core.exceptions import NotFoundException, UnauthorizedException, InvestmentException, BadRequestException
from app.models.portfolio import RiskProfile, AssetClass
from app.utils.helpers import get_current_time_ist, convert_mongo_document

# Import services
from app.services.investment_service import get_portfolio_details
from app.services.analytics_service import (
    analyze_trends,
    calculate_financial_health_score
)

# Configure logger
logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/investments",
    tags=["investments"],
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

@router.get("/recommendations", response_model=Dict[str, Any])
async def get_investment_recommendations(
    token: str = Depends(oauth2_scheme),
    risk_profile: Optional[RiskProfile] = Query(None, description="User's risk profile (overrides user's default)"),
    investment_amount: Optional[float] = Query(None, description="Amount available for investment"),
    timeframe: Optional[str] = Query("long_term", description="Investment timeframe (short_term, medium_term, long_term)"),
    goal_id: Optional[str] = Query(None, description="Related financial goal")
):
    """
    Get personalized investment recommendations based on user's profile and market conditions
    
    - **risk_profile**: User's risk tolerance (overrides default profile if provided)
    - **investment_amount**: Amount available for investment
    - **timeframe**: Investment timeframe (short_term, medium_term, long_term)
    - **goal_id**: Related financial goal ID
    """
    logger.info("Processing investment recommendations request")
    
    try:
        user_id = await get_current_user_id(token)
        
        # Get user data to determine risk profile if not provided
        if not risk_profile:
            users_collection = await get_collection("users")
            user = await users_collection.find_one({"_id": ObjectId(user_id)})
            
            if not user:
                raise NotFoundException(detail="User not found")
            
            user_risk_profile = user.get("risk_profile", "moderate")
            risk_profile = RiskProfile(user_risk_profile)
        
        # Get user's existing portfolios
        portfolios_collection = await get_collection("portfolios")
        portfolios = await portfolios_collection.find({
            "user_id": user_id,
            "is_active": True
        }).to_list(length=10)
        
        # Get user's financial health score
        financial_health = await calculate_financial_health_score(user_id)
        
        # Get related goal if provided
        goal = None
        if goal_id:
            goals_collection = await get_collection("goals")
            goal = await goals_collection.find_one({
                "_id": ObjectId(goal_id),
                "user_id": user_id
            })
            
            if not goal:
                raise NotFoundException(detail="Goal not found")
        
        # Prepare recommendation data based on risk profile
        # Low risk: More debt, less equity
        # High risk: More equity, less debt
        risk_allocations = {
            RiskProfile.CONSERVATIVE: {
                AssetClass.EQUITY: 30,
                AssetClass.DEBT: 50,
                AssetClass.CASH: 15,
                AssetClass.GOLD: 5
            },
            RiskProfile.MODERATE: {
                AssetClass.EQUITY: 50,
                AssetClass.DEBT: 35,
                AssetClass.CASH: 10,
                AssetClass.GOLD: 5
            },
            RiskProfile.BALANCED: {
                AssetClass.EQUITY: 60,
                AssetClass.DEBT: 30,
                AssetClass.CASH: 5,
                AssetClass.GOLD: 5
            },
            RiskProfile.GROWTH: {
                AssetClass.EQUITY: 70,
                AssetClass.DEBT: 20,
                AssetClass.CASH: 5,
                AssetClass.GOLD: 5
            },
            RiskProfile.AGGRESSIVE: {
                AssetClass.EQUITY: 80,
                AssetClass.DEBT: 10,
                AssetClass.CASH: 5,
                AssetClass.GOLD: 5
            }
        }
        
        # Get recommended allocation based on risk profile
        recommended_allocation = risk_allocations.get(risk_profile, risk_allocations[RiskProfile.MODERATE])
        
        # Adjust allocation based on timeframe
        if timeframe == "short_term":
            # Increase cash and debt for short-term
            adjustment = min(recommended_allocation[AssetClass.EQUITY], 20)
            recommended_allocation[AssetClass.EQUITY] -= adjustment
            recommended_allocation[AssetClass.DEBT] += adjustment // 2
            recommended_allocation[AssetClass.CASH] += adjustment // 2
        elif timeframe == "long_term":
            # Increase equity for long-term
            adjustment = min(recommended_allocation[AssetClass.DEBT], 10)
            recommended_allocation[AssetClass.DEBT] -= adjustment
            recommended_allocation[AssetClass.EQUITY] += adjustment
        
        # Get recommended instruments
        instruments_collection = await get_collection("investment_instruments")
        
        # Get top equity instruments based on risk profile
        equity_filter = {"asset_class": "equity"}
        if risk_profile in [RiskProfile.CONSERVATIVE, RiskProfile.MODERATE]:
            equity_filter["risk_rating"] = {"$lte": 3}  # Lower risk equity
        elif risk_profile == RiskProfile.BALANCED:
            equity_filter["risk_rating"] = {"$lte": 4}
        
        equity_instruments = await instruments_collection.find(equity_filter).sort(
            "historical_returns", -1
        ).limit(5).to_list(length=5)
        
        # Get top debt instruments
        debt_filter = {"asset_class": "debt"}
        if risk_profile in [RiskProfile.GROWTH, RiskProfile.AGGRESSIVE]:
            debt_filter["yield"] = {"$gte": 7}  # Higher yield debt for aggressive profiles
        
        debt_instruments = await instruments_collection.find(debt_filter).sort(
            "yield", -1
        ).limit(3).to_list(length=3)
        
        # Get gold and cash instruments
        gold_instruments = await instruments_collection.find(
            {"asset_class": "gold"}
        ).limit(1).to_list(length=1)
        
        cash_instruments = await instruments_collection.find(
            {"asset_class": "cash"}
        ).sort("liquidity", -1).limit(2).to_list(length=2)
        
        # Prepare recommendation results
        recommended_portfolio = []
        
        # Only allocate amounts if investment_amount is provided
        if investment_amount and investment_amount > 0:
            for instrument in equity_instruments:
                weight = recommended_allocation[AssetClass.EQUITY] / 100
                instrument_allocation = round(investment_amount * weight / len(equity_instruments), 2)
                recommended_portfolio.append({
                    "instrument_id": str(instrument["_id"]),
                    "name": instrument["name"],
                    "asset_class": instrument["asset_class"],
                    "allocation_percentage": round(weight * 100 / len(equity_instruments), 1),
                    "amount": instrument_allocation,
                    "expected_return": instrument.get("expected_return", 10)
                })
            
            for instrument in debt_instruments:
                weight = recommended_allocation[AssetClass.DEBT] / 100
                instrument_allocation = round(investment_amount * weight / len(debt_instruments), 2)
                recommended_portfolio.append({
                    "instrument_id": str(instrument["_id"]),
                    "name": instrument["name"],
                    "asset_class": instrument["asset_class"],
                    "allocation_percentage": round(weight * 100 / len(debt_instruments), 1),
                    "amount": instrument_allocation,
                    "expected_return": instrument.get("yield", 6)
                })
            
            # Add gold and cash instruments
            if gold_instruments:
                gold_weight = recommended_allocation[AssetClass.GOLD] / 100
                gold_allocation = round(investment_amount * gold_weight, 2)
                recommended_portfolio.append({
                    "instrument_id": str(gold_instruments[0]["_id"]),
                    "name": gold_instruments[0]["name"],
                    "asset_class": gold_instruments[0]["asset_class"],
                    "allocation_percentage": recommended_allocation[AssetClass.GOLD],
                    "amount": gold_allocation,
                    "expected_return": gold_instruments[0].get("expected_return", 7)
                })
            
            for instrument in cash_instruments:
                cash_weight = recommended_allocation[AssetClass.CASH] / 100
                cash_allocation = round(investment_amount * cash_weight / len(cash_instruments), 2)
                recommended_portfolio.append({
                    "instrument_id": str(instrument["_id"]),
                    "name": instrument["name"],
                    "asset_class": instrument["asset_class"],
                    "allocation_percentage": round(cash_weight * 100 / len(cash_instruments), 1),
                    "amount": cash_allocation,
                    "expected_return": instrument.get("yield", 3)
                })
        else:
            # Just provide instruments without amounts
            for instrument in equity_instruments:
                recommended_portfolio.append({
                    "instrument_id": str(instrument["_id"]),
                    "name": instrument["name"],
                    "asset_class": instrument["asset_class"],
                    "allocation_percentage": recommended_allocation[AssetClass.EQUITY] / len(equity_instruments),
                    "expected_return": instrument.get("expected_return", 10)
                })
            
            for instrument in debt_instruments:
                recommended_portfolio.append({
                    "instrument_id": str(instrument["_id"]),
                    "name": instrument["name"],
                    "asset_class": instrument["asset_class"],
                    "allocation_percentage": recommended_allocation[AssetClass.DEBT] / len(debt_instruments),
                    "expected_return": instrument.get("yield", 6)
                })
            
            # Add gold and cash instruments
            if gold_instruments:
                recommended_portfolio.append({
                    "instrument_id": str(gold_instruments[0]["_id"]),
                    "name": gold_instruments[0]["name"],
                    "asset_class": gold_instruments[0]["asset_class"],
                    "allocation_percentage": recommended_allocation[AssetClass.GOLD],
                    "expected_return": gold_instruments[0].get("expected_return", 7)
                })
            
            for instrument in cash_instruments:
                recommended_portfolio.append({
                    "instrument_id": str(instrument["_id"]),
                    "name": instrument["name"],
                    "asset_class": instrument["asset_class"],
                    "allocation_percentage": recommended_allocation[AssetClass.CASH] / len(cash_instruments),
                    "expected_return": instrument.get("yield", 3)
                })
        
        # Calculate overall expected return
        expected_return = sum(
            instrument["expected_return"] * instrument["allocation_percentage"] / 100 
            for instrument in recommended_portfolio
        )
        
        # Add customized investment advice based on financial health
        investment_advice = []
        
        if financial_health["score"] < 50:
            investment_advice.append("Focus on improving your financial health before making significant investments")
            investment_advice.append("Consider building an emergency fund before investing in higher-risk assets")
        elif financial_health["score"] < 70:
            investment_advice.append("Balance debt reduction with modest investments to improve financial stability")
        else:
            investment_advice.append("Your strong financial health supports a more growth-oriented investment strategy")
        
        # Add goal-specific advice if a goal was provided
        if goal:
            years_to_goal = (goal["target_date"] - get_current_time_ist()).days / 365
            
            if years_to_goal < 2:
                investment_advice.append("With your goal approaching soon, focus on capital preservation")
            elif years_to_goal < 5:
                investment_advice.append("With a medium-term goal, balance growth with moderate risk")
            else:
                investment_advice.append("With a long-term goal, you can focus more on growth-oriented investments")
        
        return {
            "risk_profile": risk_profile,
            "asset_allocation": recommended_allocation,
            "recommended_portfolio": recommended_portfolio,
            "expected_return": expected_return,
            "investment_amount": investment_amount,
            "timeframe": timeframe,
            "investment_advice": investment_advice,
            "goal_id": goal_id if goal else None,
            "generated_at": get_current_time_ist()
        }
    
    except Exception as e:
        logger.error(f"Error in get_investment_recommendations: {str(e)}")
        if isinstance(e, (NotFoundException, UnauthorizedException)):
            raise
        raise InvestmentException(detail=f"Failed to generate investment recommendations: {str(e)}")

@router.post("/execute", status_code=status.HTTP_201_CREATED, response_model=Dict[str, Any])
async def execute_investment(
    investment_data: Dict[str, Any],
    token: str = Depends(oauth2_scheme)
):
    """
    Execute an investment transaction based on recommendations
    """
    logger.info("Executing investment transaction")
    try:
        user_id = await get_current_user_id(token)

        # Validate required fields
        required_fields = ["instruments", "total_amount", "source_account_id"]
        for field in required_fields:
            if field not in investment_data:
                raise BadRequestException(detail=f"Missing required field: {field}")

        if investment_data["total_amount"] <= 0:
            raise BadRequestException(detail="Investment amount must be positive")

        instruments = investment_data["instruments"]
        if not instruments or not isinstance(instruments, list) or len(instruments) == 0:
            raise BadRequestException(detail="Must include at least one investment instrument")

        accounts_collection = await get_collection("accounts")
        source_account = None

        # Try ObjectId in _id
        try:
            source_account = await accounts_collection.find_one({
                "_id": ObjectId(investment_data["source_account_id"]),
                "user_id": user_id
            })
        except Exception:
            pass

        # Try string in _id
        if not source_account:
            source_account = await accounts_collection.find_one({
                "_id": investment_data["source_account_id"],
                "user_id": user_id
            })

        # Try string in id field
        if not source_account:
            source_account = await accounts_collection.find_one({
                "id": investment_data["source_account_id"],
                "user_id": user_id
            })

        if not source_account:
            raise NotFoundException(detail="Source account not found")

        if source_account.get("current_balance", 0) < investment_data["total_amount"]:
            raise BadRequestException(detail="Insufficient funds in source account")
        
        # Determine if creating new portfolio or adding to existing
        portfolio_id = investment_data.get("portfolio_id")
        portfolio = None
        portfolios_collection = await get_collection("portfolios")
        
        if portfolio_id:
            # Check if portfolio exists and belongs to user
            portfolio = await portfolios_collection.find_one({
                "_id": ObjectId(portfolio_id),
                "user_id": user_id
            })
            
            if not portfolio:
                raise NotFoundException(detail="Portfolio not found")
        else:
            # Create new portfolio
            current_time = get_current_time_ist()
            new_portfolio = {
                "user_id": user_id,
                "name": investment_data.get("portfolio_name", "Investment Portfolio"),
                "description": investment_data.get("description", "Created from investment recommendations"),
                "portfolio_type": investment_data.get("portfolio_type", "custom"),
                "risk_profile": investment_data.get("risk_profile", "moderate"),
                "holdings": [],
                "performance": {
                    "current_value": 0,
                    "invested_value": 0,
                    "total_gain_loss": 0,
                    "total_gain_loss_percentage": 0,
                    "last_updated": current_time
                },
                "asset_allocation": {
                    "equity_percentage": 0,
                    "debt_percentage": 0,
                    "cash_percentage": 0,
                    "gold_percentage": 0,
                    "alternative_percentage": 0,
                    "crypto_percentage": 0
                },
                "created_at": current_time,
                "updated_at": current_time,
                "is_active": True
            }
            
            result = await portfolios_collection.insert_one(new_portfolio)
            portfolio_id = result.inserted_id
            portfolio = await portfolios_collection.find_one({"_id": portfolio_id})
        
        # Create investments in portfolio
        current_time = get_current_time_ist()
        instruments_collection = await get_collection("investment_instruments")
        transactions_collection = await get_collection("transactions")
        
        # Prepare holdings to add to portfolio
        new_holdings = []
        total_invested = 0
        
        for instrument_data in instruments:
            # Validate instrument data
            instrument_id = instrument_data.get("instrument_id")
            amount = instrument_data.get("amount")
            
            if not instrument_id or not amount or amount <= 0:
                continue
            
            # Get instrument details
            instrument = await instruments_collection.find_one({"_id": ObjectId(instrument_id)})
            if not instrument:
                logger.warning(f"Instrument not found: {instrument_id}")
                continue
            
            # Calculate units based on current price
            current_price = instrument.get("current_price", 1)
            units = amount / current_price if current_price > 0 else 0
            
            # Create holding
            holding = {
                "id": str(ObjectId()),
                "instrument_id": str(instrument["_id"]),
                "instrument_name": instrument["name"],
                "instrument_type": instrument["instrument_type"],
                "asset_class": instrument["asset_class"],
                "units": units,
                "average_buy_price": current_price,
                "current_price": current_price,
                "current_value": amount,
                "invested_amount": amount,
                "unrealized_gain_loss": 0,
                "unrealized_gain_loss_percentage": 0,
                "last_price_update": current_time,
                "sector": instrument.get("sector"),
                "industry": instrument.get("industry"),
                "created_at": current_time,
                "updated_at": current_time
            }
            
            new_holdings.append(holding)
            total_invested += amount
        
        # Update portfolio with new holdings
        portfolio_holdings = portfolio.get("holdings", [])
        portfolio_holdings.extend(new_holdings)
        
        # Update portfolio performance metrics
        total_current_value = sum(h.get("current_value", 0) for h in portfolio_holdings)
        total_invested_value = sum(h.get("invested_amount", 0) for h in portfolio_holdings)
        total_gain_loss = total_current_value - total_invested_value
        gain_loss_percentage = (total_gain_loss / total_invested_value * 100) if total_invested_value > 0 else 0
        
        performance_update = {
            "current_value": total_current_value,
            "invested_value": total_invested_value,
            "total_gain_loss": total_gain_loss,
            "total_gain_loss_percentage": gain_loss_percentage,
            "last_updated": current_time
        }
        
        # Calculate asset allocation
        asset_class_totals = {}
        for holding in portfolio_holdings:
            asset_class = holding.get("asset_class")
            if asset_class not in asset_class_totals:
                asset_class_totals[asset_class] = 0
            asset_class_totals[asset_class] += holding.get("current_value", 0)
        
        # Calculate asset allocation percentages
        allocation_update = {
            "equity_percentage": 0,
            "debt_percentage": 0,
            "cash_percentage": 0,
            "gold_percentage": 0,
            "alternative_percentage": 0,
            "crypto_percentage": 0
        }
        
        if total_current_value > 0:
            for asset_class, value in asset_class_totals.items():
                percentage = value / total_current_value * 100
                if asset_class == AssetClass.EQUITY:
                    allocation_update["equity_percentage"] = percentage
                elif asset_class == AssetClass.DEBT:
                    allocation_update["debt_percentage"] = percentage
                elif asset_class == AssetClass.CASH:
                    allocation_update["cash_percentage"] = percentage
                elif asset_class == AssetClass.GOLD:
                    allocation_update["gold_percentage"] = percentage
                elif asset_class == AssetClass.ALTERNATIVE:
                    allocation_update["alternative_percentage"] = percentage
                elif asset_class == AssetClass.CRYPTO:
                    allocation_update["crypto_percentage"] = percentage
        
        # Update portfolio
        await portfolios_collection.update_one(
            {"_id": portfolio_id},
            {
                "$set": {
                    "holdings": portfolio_holdings,
                    "performance": performance_update,
                    "asset_allocation": allocation_update,
                    "updated_at": current_time
                }
            }
        )
        
        # Create transaction record for withdrawal
        transaction = {
            "user_id": user_id,
            "account_id": investment_data["source_account_id"],
            "amount": investment_data["total_amount"],
            "transaction_type": "debit",
            "category": "investments",
            "description": f"Investment in {investment_data.get('portfolio_name', 'portfolio')}",
            "date": current_time,
            "status": "completed",
            "created_at": current_time,
            "updated_at": current_time,
            "portfolio_id": str(portfolio_id)
        }
        
        await transactions_collection.insert_one(transaction)
        
        # Update source account balance
        await accounts_collection.update_one(
            {"_id": ObjectId(investment_data["source_account_id"])},
            {
                "$inc": {"current_balance": -investment_data["total_amount"]},
                "$set": {"last_balance_update": current_time}
            }
        )
        
        # Return updated portfolio details
        updated_portfolio = await portfolios_collection.find_one({"_id": portfolio_id})
        return {
            "status": "success",
            "message": "Investment executed successfully",
            "portfolio_id": str(portfolio_id),
            "total_invested": total_invested,
            "holdings_added": len(new_holdings),
            "portfolio": convert_mongo_document(updated_portfolio)
        }
    
    except Exception as e:
        logger.error(f"Error in execute_investment: {str(e)}")
        if isinstance(e, (NotFoundException, UnauthorizedException, BadRequestException)):
            raise
        raise InvestmentException(detail=f"Failed to execute investment: {str(e)}")

@router.get("/performance", response_model=Dict[str, Any])
async def get_performance_metrics(
    token: str = Depends(oauth2_scheme),
    portfolio_id: Optional[str] = Query(None, description="Portfolio ID (returns metrics for specific portfolio)"),
    timeframe: str = Query("all", description="Timeframe for analysis (month, quarter, year, all)"),
    include_trends: bool = Query(True, description="Include trend analysis")
):
    """
    Get detailed performance metrics for investments
    
    - **portfolio_id**: Portfolio ID (returns metrics for specific portfolio)
    - **timeframe**: Timeframe for analysis (month, quarter, year, all)
    - **include_trends**: Include trend analysis
    """
    logger.info("Getting investment performance metrics")
    
    try:
        user_id = await get_current_user_id(token)
        
        # Handle timeframe for date filtering
        end_date = get_current_time_ist()
        if timeframe == "month":
            start_date = end_date - timedelta(days=30)
        elif timeframe == "quarter":
            start_date = end_date - timedelta(days=90)
        elif timeframe == "year":
            start_date = end_date - timedelta(days=365)
        else:  # "all"
            start_date = datetime(2000, 1, 1)  # Far past date to include all data
        
        # Get portfolio data
        if portfolio_id:
            # Get specific portfolio
            portfolio = await get_portfolio_details(portfolio_id)
            
            # Check if portfolio belongs to user
            if portfolio["user_id"] != user_id:
                raise UnauthorizedException(detail="Not authorized to access this portfolio")
            
            # Get performance metrics
            performance = portfolio.get("performance", {})
            
            result = {
                "portfolio_id": portfolio_id,
                "portfolio_name": portfolio.get("name"),
                "current_value": performance.get("current_value", 0),
                "invested_value": performance.get("invested_value", 0),
                "total_gain_loss": performance.get("total_gain_loss", 0),
                "total_gain_loss_percentage": performance.get("total_gain_loss_percentage", 0),
                "asset_allocation": portfolio.get("asset_allocation", {}),
                "holdings_count": len(portfolio.get("holdings", [])),
                "last_updated": performance.get("last_updated")
            }
            
            # Add risk-adjusted metrics if available
            if "volatility" in performance:
                result["volatility"] = performance["volatility"]
                
            if "sharpe_ratio" in performance:
                result["sharpe_ratio"] = performance["sharpe_ratio"]
                
            # Get top performing holdings
            holdings = portfolio.get("holdings", [])
            holdings_sorted = sorted(
                holdings,
                key=lambda h: h.get("unrealized_gain_loss_percentage", 0),
                reverse=True
            )
            
            top_performers = []
            bottom_performers = []
            
            for holding in holdings_sorted[:3]:
                top_performers.append({
                    "name": holding.get("instrument_name"),
                    "asset_class": holding.get("asset_class"),
                    "gain_percentage": holding.get("unrealized_gain_loss_percentage", 0),
                    "gain_amount": holding.get("unrealized_gain_loss", 0),
                    "current_value": holding.get("current_value", 0)
                })
            
            for holding in holdings_sorted[-3:]:
                bottom_performers.append({
                    "name": holding.get("instrument_name"),
                    "asset_class": holding.get("asset_class"),
                    "gain_percentage": holding.get("unrealized_gain_loss_percentage", 0),
                    "gain_amount": holding.get("unrealized_gain_loss", 0),
                    "current_value": holding.get("current_value", 0)
                })
            
            result["top_performers"] = top_performers
            result["bottom_performers"] = bottom_performers
            
            if include_trends:
                # Get trend analysis for this portfolio
                trend_data = await analyze_investment_trends(user_id, portfolio_id)
                result["trends"] = trend_data
            
        else:
            # Get all portfolios for user
            portfolios_collection = await get_collection("portfolios")
            portfolios = await portfolios_collection.find({
                "user_id": user_id,
                "is_active": True
            }).to_list(length=20)
            
            if not portfolios:
                return {
                    "total_investment_value": 0,
                    "total_gain_loss": 0,
                    "total_gain_loss_percentage": 0,
                    "portfolios": []
                }
            
            # Calculate aggregate metrics
            total_current_value = 0
            total_invested_value = 0
            total_gain_loss = 0
            portfolio_summaries = []
            
            for portfolio in portfolios:
                performance = portfolio.get("performance", {})
                current_value = performance.get("current_value", 0)
                invested_value = performance.get("invested_value", 0)
                gain_loss = performance.get("total_gain_loss", 0)
                gain_loss_pct = performance.get("total_gain_loss_percentage", 0)
                
                total_current_value += current_value
                total_invested_value += invested_value
                total_gain_loss += gain_loss
                
                portfolio_summaries.append({
                    "id": str(portfolio["_id"]),
                    "name": portfolio["name"],
                    "current_value": current_value,
                    "gain_loss": gain_loss,
                    "gain_loss_percentage": gain_loss_pct,
                    "holdings_count": len(portfolio.get("holdings", [])),
                    "risk_profile": portfolio.get("risk_profile")
                })
            
            # Calculate overall percentage gain/loss
            overall_gain_loss_pct = 0
            if total_invested_value > 0:
                overall_gain_loss_pct = (total_gain_loss / total_invested_value) * 100
            
            result = {
                "total_investment_value": total_current_value,
                "total_invested_value": total_invested_value,
                "total_gain_loss": total_gain_loss,
                "total_gain_loss_percentage": overall_gain_loss_pct,
                "portfolios": portfolio_summaries
            }
            
            if include_trends:
                # Get overall trend analysis
                trend_data = await analyze_investment_trends(user_id)
                result["trends"] = trend_data
        
        return result
    
    except Exception as e:
        logger.error(f"Error in get_performance_metrics: {str(e)}")
        if isinstance(e, (NotFoundException, UnauthorizedException)):
            raise
        raise InvestmentException(detail=f"Failed to get performance metrics: {str(e)}")

# Private helper function for investment trends analysis
async def analyze_investment_trends(user_id: str, portfolio_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Analyze investment trends over time
    
    Args:
        user_id: User ID
        portfolio_id: Optional portfolio ID for specific portfolio analysis
    
    Returns:
        Trend analysis data
    """
    try:
        # Get investment transactions
        transactions_collection = await get_collection("transactions")
        
        # Build query for transactions
        query = {
            "user_id": user_id,
            "category": "investments"
        }
        
        if portfolio_id:
            query["portfolio_id"] = portfolio_id
        
        # Get investment transactions
        transactions = await transactions_collection.find(query).sort("date", 1).to_list(length=1000)
        
        if not transactions:
            return {
                "data_points": [],
                "trend_direction": "neutral",
                "avg_return": 0
            }
        
        # Group transactions by month
        monthly_data = {}
        
        for txn in transactions:
            month_key = txn["date"].strftime("%Y-%m")
            if month_key not in monthly_data:
                monthly_data[month_key] = {
                    "investments": 0,
                    "withdrawals": 0,
                    "net_flow": 0
                }
            
            if txn["transaction_type"] == "debit":
                monthly_data[month_key]["investments"] += txn["amount"]
                monthly_data[month_key]["net_flow"] -= txn["amount"]
            else:  # credit
                monthly_data[month_key]["withdrawals"] += txn["amount"]
                monthly_data[month_key]["net_flow"] += txn["amount"]
        
        # Get portfolio value history if available
        value_history = []
        
        if portfolio_id:
            portfolio_history_collection = await get_collection("portfolio_history")
            history_records = await portfolio_history_collection.find({
                "portfolio_id": portfolio_id
            }).sort("date", 1).to_list(length=100)
            
            if history_records:
                value_history = [
                    {"date": record["date"].strftime("%Y-%m"), "value": record["value"]}
                    for record in history_records
                ]
        
        # Prepare result with analysis
        data_points = []
        total_investment = 0
        
        for month, data in sorted(monthly_data.items()):
            total_investment += data["investments"] - data["withdrawals"]
            
            point = {
                "date": month,
                "investments": data["investments"],
                "withdrawals": data["withdrawals"],
                "net_flow": data["net_flow"],
                "cumulative_investment": total_investment
            }
            
            # Add portfolio value if available
            matching_history = next((h for h in value_history if h["date"] == month), None)
            if matching_history:
                point["portfolio_value"] = matching_history["value"]
            
            data_points.append(point)
        
        # Calculate trend direction and avg return
        trend_direction = "neutral"
        avg_return = 0
        
        if len(data_points) >= 2 and portfolio_id:
            first_with_value = next((p for p in data_points if "portfolio_value" in p), None)
            last_with_value = next((p for p in reversed(data_points) if "portfolio_value" in p), None)
            
            if first_with_value and last_with_value and first_with_value != last_with_value:
                initial_value = first_with_value["portfolio_value"]
                final_value = last_with_value["portfolio_value"]
                value_change = final_value - initial_value
                
                if value_change > 0:
                    trend_direction = "increasing"
                else:
                    trend_direction = "decreasing"
                
                # Simplified average return calculation
                months_between = len(data_points)
                if months_between > 0 and initial_value > 0:
                    avg_return = (value_change / initial_value) / months_between * 100
        
        return {
            "data_points": data_points,
            "trend_direction": trend_direction,
            "avg_return": avg_return
        }
        
    except Exception as e:
        logger.error(f"Error in analyze_investment_trends: {str(e)}")
        return {
            "data_points": [],
            "trend_direction": "neutral",
            "avg_return": 0,
            "error": str(e)
        }