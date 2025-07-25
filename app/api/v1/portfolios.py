from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
import logging
from fastapi import APIRouter, Depends, HTTPException, status, Path, Query
from bson import ObjectId

from app.config.database import get_collection
from app.core.security import oauth2_scheme, decode_access_token
from app.core.exceptions import NotFoundException, UnauthorizedException, ExternalAPIException, BadRequestException, InvestmentException
from app.schemas.portfolio import (
    PortfolioResponse,
    PortfolioSummaryResponse,
    PortfolioCreate,
    PortfolioUpdate,
    HoldingCreate,
    HoldingUpdate,
    HoldingResponse,
    RebalanceRecommendation,
    HoldingTransaction,
    PortfolioPerformanceResponse,
    AssetAllocationResponse
)
from app.models.portfolio import Portfolio, AssetClass, InvestmentType, RiskProfile, InvestmentHolding, PortfolioPerformance
from app.utils.helpers import get_current_time_ist, convert_mongo_document
from app.services.investment_service import (
    create_portfolio, 
    add_holdings, 
    update_holding, 
    remove_holding, 
    get_portfolio_details
)

# Configure logger
logger = logging.getLogger(__name__)
logger.debug(f"Creating portfolios router with prefix: /portfolios")

router = APIRouter(
    prefix="/portfolios",
    tags=["portfolios"],
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

@router.get("/", response_model=List[PortfolioSummaryResponse])
async def list_portfolios(
    token: str = Depends(oauth2_scheme),
    active_only: bool = Query(True, description="Only show active portfolios"),
    risk_profile: Optional[RiskProfile] = Query(None, description="Filter by risk profile")
):
    """
    List all portfolios for the current user
    
    - **active_only**: Only return active portfolios (default: True)
    - **risk_profile**: Filter by risk profile (optional)
    """
    user_id = await get_current_user_id(token)
    
    # Build filter
    filter_query = {"user_id": user_id}
    
    if active_only:
        filter_query["is_active"] = True
    
    if risk_profile:
        filter_query["risk_profile"] = risk_profile
    
    # Get portfolios from database
    portfolios_collection = await get_collection("portfolios")
    portfolios = await portfolios_collection.find(filter_query).to_list(length=100)
    
    # Convert to response model
    result = []
    for portfolio in portfolios:
        portfolio_data = convert_mongo_document(portfolio)
        result.append(PortfolioSummaryResponse(
            id=portfolio_data["id"],
            name=portfolio_data["name"],
            current_value=portfolio_data.get("performance", {}).get("current_value", 0),
            invested_value=portfolio_data.get("performance", {}).get("invested_value", 0),
            total_gain_loss_percentage=portfolio_data.get("performance", {}).get("total_gain_loss_percentage", 0),
            risk_profile=portfolio_data["risk_profile"],
            created_at=portfolio_data["created_at"]
        ))
    
    return result

@router.get("/{portfolio_id}", response_model=PortfolioResponse)
async def get_portfolio(
    portfolio_id: str = Path(..., description="Portfolio ID"),
    token: str = Depends(oauth2_scheme)
):
    """
    Get detailed information about a specific portfolio
    """
    user_id = await get_current_user_id(token)
    
    # Get portfolio from database
    portfolios_collection = await get_collection("portfolios")
    
    # Try both string ID and MongoDB ObjectId
    portfolio = None
    
    try:
        object_id = ObjectId(portfolio_id)
        portfolio = await portfolios_collection.find_one({
            "_id": object_id,
            "user_id": user_id
        })
    except Exception:
        # If conversion to ObjectId fails, try with string ID
        portfolio = await portfolios_collection.find_one({
            "id": portfolio_id,
            "user_id": user_id
        })
    
    if not portfolio:
        raise NotFoundException(detail="Portfolio not found")
    
    return convert_mongo_document(portfolio)

@router.post("/", status_code=status.HTTP_201_CREATED, response_model=PortfolioResponse)
async def create_new_portfolio(
    portfolio_data: PortfolioCreate,
    token: str = Depends(oauth2_scheme)
):
    """
    Create a new investment portfolio
    """
    user_id = await get_current_user_id(token)
    
    # Verify user ID matches the requested user_id for security
    if user_id != portfolio_data.user_id:
        raise UnauthorizedException(detail="User ID mismatch")
    
    # Create portfolio using investment service
    try:
        new_portfolio = await create_portfolio(user_id, portfolio_data.dict())
        return convert_mongo_document(new_portfolio)
    except Exception as e:
        logger.error(f"Error creating portfolio: {str(e)}")
        if isinstance(e, (NotFoundException, BadRequestException, InvestmentException)):
            raise e
        raise BadRequestException(detail=f"Error creating portfolio: {str(e)}")

@router.put("/{portfolio_id}", response_model=PortfolioResponse)
async def update_portfolio(
    portfolio_data: PortfolioUpdate,
    portfolio_id: str = Path(..., description="Portfolio ID"),
    token: str = Depends(oauth2_scheme)
):
    """
    Update portfolio information
    """
    user_id = await get_current_user_id(token)
    
    # Check if portfolio exists and belongs to user
    portfolios_collection = await get_collection("portfolios")
    
    # Try both string ID and MongoDB ObjectId
    try:
        object_id = ObjectId(portfolio_id)
        portfolio = await portfolios_collection.find_one({
            "_id": object_id,
            "user_id": user_id
        })
    except Exception:
        # If conversion to ObjectId fails, try with string ID
        portfolio = await portfolios_collection.find_one({
            "id": portfolio_id,
            "user_id": user_id
        })
    
    if not portfolio:
        raise NotFoundException(detail="Portfolio not found")
    
    # Prepare update data
    update_data = {k: v for k, v in portfolio_data.dict(exclude_unset=True).items() if v is not None}
    update_data["updated_at"] = get_current_time_ist()
    
    # If setting this as default, unset default on other portfolios
    if update_data.get("is_default", False):
        await portfolios_collection.update_many(
            {"user_id": user_id, "is_default": True},
            {"$set": {"is_default": False}}
        )
    
    # Update portfolio
    await portfolios_collection.update_one(
        {"_id": portfolio["_id"]},
        {"$set": update_data}
    )
    
    # Get updated portfolio
    updated_portfolio = await portfolios_collection.find_one({"_id": portfolio["_id"]})
    return convert_mongo_document(updated_portfolio)

@router.post("/{portfolio_id}/holdings", response_model=PortfolioResponse)
async def add_portfolio_holdings(
    holdings: List[HoldingCreate],
    portfolio_id: str = Path(..., description="Portfolio ID"),
    token: str = Depends(oauth2_scheme)
):
    """
    Add holdings to a portfolio
    """
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"Adding holdings to portfolio {portfolio_id}")
    
    user_id = await get_current_user_id(token)
    
    # Check if portfolio exists and belongs to user
    portfolios_collection = await get_collection("portfolios")
    
    # Try different ID formats
    portfolio = None
    
    # First, try with MongoDB ObjectId for both portfolio_id and user_id
    try:
        object_id = ObjectId(portfolio_id)
        object_user_id = ObjectId(user_id) if isinstance(user_id, str) else user_id
        
        portfolio = await portfolios_collection.find_one({
            "_id": object_id,
            "user_id": user_id
        })
        
        # If not found, try with string user_id
        if not portfolio:
            portfolio = await portfolios_collection.find_one({
                "_id": object_id,
                "user_id": str(object_user_id)
            })
            
        # Still not found, try with string representations
        if not portfolio:
            portfolio = await portfolios_collection.find_one({
                "_id": object_id
            })
    except Exception as e:
        logger.debug(f"Failed to query with ObjectId: {str(e)}")
    
    # If still not found, try with string ID field
    if not portfolio:
        try:
            portfolio = await portfolios_collection.find_one({
                "id": portfolio_id,
                "user_id": user_id
            })
        except Exception as e:
            logger.debug(f"Failed to query with string ID: {str(e)}")
            
    # Final attempt - just look for the ID without user constraint
    if not portfolio:
        try:
            portfolio = await portfolios_collection.find_one({
                "$or": [
                    {"_id": ObjectId(portfolio_id)},
                    {"id": portfolio_id}
                ]
            })
            
            # Verify ownership if found
            if portfolio and portfolio.get("user_id") != user_id and str(portfolio.get("user_id")) != user_id:
                portfolio = None
                
        except Exception as e:
            logger.debug(f"Final attempt failed: {str(e)}")
    
    if not portfolio:
        raise NotFoundException(detail="Portfolio not found")
    
    # Add holdings using investment service
    try:
        # Convert each holding to a dict
        holdings_data = [holding.dict() for holding in holdings]
        
        # Use the correct portfolio ID format for the service function
        portfolio_id_for_service = str(portfolio["_id"])
        
        logger.debug(f"Calling add_holdings with portfolio_id: {portfolio_id_for_service}")
        updated_portfolio = await add_holdings(portfolio_id_for_service, holdings_data)
        
        return convert_mongo_document(updated_portfolio)
    except Exception as e:
        logger.error(f"Error adding holdings: {str(e)}", exc_info=True)
        if isinstance(e, (NotFoundException, BadRequestException, InvestmentException)):
            raise e
        raise BadRequestException(detail=f"Error adding holdings: {str(e)}")

@router.post("/analyze", response_model=Dict[str, Any])
async def analyze_portfolio(
    portfolio_id: str = Query(..., description="Portfolio ID to analyze"),
    token: str = Depends(oauth2_scheme)
):
    """
    Analyze a portfolio and provide insights on performance, risk, and diversification
    """
    user_id = await get_current_user_id(token)
    
    # Check if portfolio exists and belongs to user
    portfolios_collection = await get_collection("portfolios")
    
    try:
        object_id = ObjectId(portfolio_id)
        portfolio = await portfolios_collection.find_one({
            "_id": object_id,
            "user_id": user_id
        })
    except Exception:
        portfolio = await portfolios_collection.find_one({
            "id": portfolio_id,
            "user_id": user_id
        })
    
    if not portfolio:
        raise NotFoundException(detail="Portfolio not found")
    
    # Get portfolio details
    portfolio_data = convert_mongo_document(portfolio)
    
    # Calculate portfolio metrics
    try:
        # Calculate basic portfolio statistics
        holdings = portfolio_data.get("holdings", [])
        total_value = sum(holding.get("current_value", 0) for holding in holdings)
        total_invested = sum(holding.get("invested_amount", 0) for holding in holdings)
        total_gain_loss = total_value - total_invested
        total_gain_loss_pct = (total_gain_loss / total_invested * 100) if total_invested > 0 else 0
        
        # Asset allocation analysis
        asset_allocation = {}
        for holding in holdings:
            asset_class = holding.get("asset_class", "UNKNOWN")
            if asset_class not in asset_allocation:
                asset_allocation[asset_class] = 0
            asset_allocation[asset_class] += holding.get("current_value", 0)
        
        # Convert absolute values to percentages
        for asset_class in asset_allocation:
            asset_allocation[asset_class] = (asset_allocation[asset_class] / total_value * 100) if total_value > 0 else 0
        
        # Risk analysis (simplified)
        risk_score = 0
        if portfolio_data.get("risk_profile") == RiskProfile.CONSERVATIVE:
            risk_score = 1
        elif portfolio_data.get("risk_profile") == RiskProfile.MODERATE:
            risk_score = 2
        elif portfolio_data.get("risk_profile") == RiskProfile.BALANCED:
            risk_score = 3
        elif portfolio_data.get("risk_profile") == RiskProfile.GROWTH:
            risk_score = 4
        elif portfolio_data.get("risk_profile") == RiskProfile.AGGRESSIVE:
            risk_score = 5
        
        # Diversification score (simplified)
        diversification_score = min(len(asset_allocation) * 2, 10)  # 0-10 scale
        
        # Return analysis results
        return {
            "portfolio_id": portfolio_data["id"],
            "name": portfolio_data["name"],
            "summary": {
                "total_value": total_value,
                "total_invested": total_invested,
                "total_gain_loss": total_gain_loss,
                "total_gain_loss_percentage": total_gain_loss_pct,
                "number_of_holdings": len(holdings)
            },
            "asset_allocation": asset_allocation,
            "risk_analysis": {
                "risk_profile": portfolio_data.get("risk_profile"),
                "risk_score": risk_score,
                "diversification_score": diversification_score,
                "concentration_risk": len([h for h in holdings if h.get("current_value", 0) / total_value > 0.1]) if total_value > 0 else 0
            },
            "recommendations": [
                "Consider rebalancing your portfolio to match your target allocation",
                f"Your portfolio has a {portfolio_data.get('risk_profile')} risk profile",
                "Regular investment through SIP can help reduce market timing risk"
            ],
            "analyzed_at": get_current_time_ist()
        }
    except Exception as e:
        logger.error(f"Error analyzing portfolio: {str(e)}")
        raise BadRequestException(detail=f"Error analyzing portfolio: {str(e)}")

@router.get("/recommendations", response_model=List[Dict[str, Any]])
async def get_investment_recommendations(
    risk_profile: Optional[RiskProfile] = Query(None, description="User's risk profile"),
    investment_amount: Optional[float] = Query(None, description="Amount available for investment"),
    token: str = Depends(oauth2_scheme)
):
    """
    Get personalized investment recommendations based on risk profile and available amount
    """
    logger = logging.getLogger(__name__)
    logger.info("Starting investment recommendations process")
    
    try:
        user_id = await get_current_user_id(token)
        logger.info(f"Getting investment recommendations for user {user_id}")
        
        # Get user details if risk profile not provided
        if not risk_profile:
            users_collection = await get_collection("users")
            logger.debug(f"Looking up user with ID: {user_id}")
            
            # Try different formats for user_id
            user = None
            try:
                # Try with ObjectId first (most common format in MongoDB)
                try:
                    object_id = ObjectId(user_id)
                    user = await users_collection.find_one({"_id": object_id})
                    logger.debug(f"Tried looking up user with ObjectId: {object_id}, found: {bool(user)}")
                except Exception as e:
                    logger.debug(f"Failed to convert user_id to ObjectId: {user_id}, error: {str(e)}")
                
                # Try with string ID if ObjectId didn't work
                if not user:
                    user = await users_collection.find_one({"id": user_id})
                    logger.debug(f"Tried looking up user with string ID, found: {bool(user)}")
                
                # Try with string as _id
                if not user:
                    user = await users_collection.find_one({"_id": user_id})
                    logger.debug(f"Tried looking up user with string _id, found: {bool(user)}")
                
                # Try matching user field to token ID exactly as string
                if not user:
                    user = await users_collection.find_one({"id": str(user_id)})
                    logger.debug(f"Tried looking up user with string id field, found: {bool(user)}")
                    
                logger.debug(f"User found: {bool(user)}")
            except Exception as e:
                logger.error(f"Error finding user: {str(e)}", exc_info=True)
            
            # Get risk profile from user if available, otherwise use default
            if user and user.get("risk_profile"):
                risk_profile = user.get("risk_profile")
                logger.debug(f"Using user's risk profile: {risk_profile}")
            else:
                risk_profile = RiskProfile.MODERATE  # Default to moderate risk
                logger.debug(f"Using default risk profile: {risk_profile}")
        
        # Define recommendation templates based on risk profile
        recommendations = []
        logger.info(f"Generating recommendations for risk profile: {risk_profile}")
        
        if risk_profile == RiskProfile.CONSERVATIVE:
            recommendations = [
                {
                    "asset_class": AssetClass.DEBT,
                    "allocation_percentage": 70,
                    "instruments": [
                        {"name": "Debt Mutual Fund", "type": InvestmentType.MUTUAL_FUND, "percentage": 40},
                        {"name": "Fixed Deposit", "type": InvestmentType.FD, "percentage": 30}
                    ],
                    "description": "Conservative portfolio with focus on capital preservation"
                },
                {
                    "asset_class": AssetClass.EQUITY,
                    "allocation_percentage": 20,
                    "instruments": [
                        {"name": "Large Cap Fund", "type": InvestmentType.MUTUAL_FUND, "percentage": 20}
                    ],
                    "description": "Limited equity exposure through large-cap funds"
                },
                {
                    "asset_class": AssetClass.CASH,
                    "allocation_percentage": 10,
                    "instruments": [
                        {"name": "Liquid Fund", "type": InvestmentType.MUTUAL_FUND, "percentage": 10}
                    ],
                    "description": "Cash equivalent for emergencies and short-term needs"
                }
            ]
        elif risk_profile == RiskProfile.MODERATE:
            recommendations = [
                {
                    "asset_class": AssetClass.DEBT,
                    "allocation_percentage": 50,
                    "instruments": [
                        {"name": "Corporate Bond Fund", "type": InvestmentType.MUTUAL_FUND, "percentage": 30},
                        {"name": "Government Bond Fund", "type": InvestmentType.MUTUAL_FUND, "percentage": 20}
                    ],
                    "description": "Balanced debt exposure for stability"
                },
                {
                    "asset_class": AssetClass.EQUITY,
                    "allocation_percentage": 40,
                    "instruments": [
                        {"name": "Large Cap Fund", "type": InvestmentType.MUTUAL_FUND, "percentage": 20},
                        {"name": "Mid Cap Fund", "type": InvestmentType.MUTUAL_FUND, "percentage": 20}
                    ],
                    "description": "Moderate equity exposure for growth potential"
                },
                {
                    "asset_class": AssetClass.GOLD,
                    "allocation_percentage": 5,
                    "instruments": [
                        {"name": "Gold ETF", "type": InvestmentType.ETF, "percentage": 5}
                    ],
                    "description": "Gold as a hedge against inflation"
                },
                {
                    "asset_class": AssetClass.CASH,
                    "allocation_percentage": 5,
                    "instruments": [
                        {"name": "Liquid Fund", "type": InvestmentType.MUTUAL_FUND, "percentage": 5}
                    ],
                    "description": "Small cash component for liquidity"
                }
            ]
        elif risk_profile in [RiskProfile.BALANCED, RiskProfile.GROWTH, RiskProfile.AGGRESSIVE]:
            # Higher risk profiles
            equity_percentage = 60 if risk_profile == RiskProfile.BALANCED else 75 if risk_profile == RiskProfile.GROWTH else 85
            debt_percentage = 100 - equity_percentage - 5  # 5% for alternative

            recommendations = [
                {
                    "asset_class": AssetClass.EQUITY,
                    "allocation_percentage": equity_percentage,
                    "instruments": [
                        {"name": "Large Cap Fund", "type": InvestmentType.MUTUAL_FUND, "percentage": equity_percentage * 0.3},
                        {"name": "Mid Cap Fund", "type": InvestmentType.MUTUAL_FUND, "percentage": equity_percentage * 0.4},
                        {"name": "Small Cap Fund", "type": InvestmentType.MUTUAL_FUND, "percentage": equity_percentage * 0.3}
                    ],
                    "description": f"High equity allocation ({equity_percentage}%) for long-term growth"
                },
                {
                    "asset_class": AssetClass.DEBT,
                    "allocation_percentage": debt_percentage,
                    "instruments": [
                        {"name": "Short Duration Fund", "type": InvestmentType.MUTUAL_FUND, "percentage": debt_percentage}
                    ],
                    "description": "Limited debt exposure for stability"
                },
                {
                    "asset_class": AssetClass.ALTERNATIVE,
                    "allocation_percentage": 5,
                    "instruments": [
                        {"name": "REITs", "type": InvestmentType.REAL_ESTATE, "percentage": 5}
                    ],
                    "description": "Alternative investments for diversification"
                }
            ]
        
        # Calculate amount allocation if investment amount provided
        if investment_amount:
            logger.debug(f"Calculating amounts for investment: {investment_amount}")
            for recommendation in recommendations:
                recommendation["amount"] = investment_amount * (recommendation["allocation_percentage"] / 100)
                for instrument in recommendation["instruments"]:
                    instrument["amount"] = investment_amount * (instrument["percentage"] / 100)
        
        logger.info(f"Successfully generated {len(recommendations)} recommendations")
        return recommendations
        
    except Exception as e:
        # Don't re-raise exceptions that could have come from other functions
        logger.error(f"Error generating investment recommendations: {str(e)}", exc_info=True)
        
        # Always provide recommendations, even if there's an error
        logger.info("Generating default recommendations due to error")
        default_recommendations = [
            {
                "asset_class": AssetClass.EQUITY,
                "allocation_percentage": 60,
                "instruments": [
                    {"name": "Large Cap Index Fund", "type": InvestmentType.MUTUAL_FUND, "percentage": 60}
                ],
                "description": "Default balanced recommendation"
            },
            {
                "asset_class": AssetClass.DEBT,
                "allocation_percentage": 40,
                "instruments": [
                    {"name": "Debt Fund", "type": InvestmentType.MUTUAL_FUND, "percentage": 40}
                ],
                "description": "Default stability component"
            }
        ]
        
        # Calculate amount allocation if investment amount provided
        if investment_amount:
            for recommendation in default_recommendations:
                recommendation["amount"] = investment_amount * (recommendation["allocation_percentage"] / 100)
                for instrument in recommendation["instruments"]:
                    instrument["amount"] = investment_amount * (instrument["percentage"] / 100)
        
        return default_recommendations

@router.delete("/{portfolio_id}", status_code=status.HTTP_200_OK)
async def delete_portfolio(
    portfolio_id: str = Path(..., description="Portfolio ID"),
    token: str = Depends(oauth2_scheme)
):
    """
    Delete a portfolio or mark it as inactive
    """
    user_id = await get_current_user_id(token)
    
    # Check if portfolio exists and belongs to user
    portfolios_collection = await get_collection("portfolios")
    
    try:
        object_id = ObjectId(portfolio_id)
        portfolio = await portfolios_collection.find_one({
            "_id": object_id,
            "user_id": user_id
        })
    except Exception:
        portfolio = await portfolios_collection.find_one({
            "id": portfolio_id,
            "user_id": user_id
        })
    
    if not portfolio:
        raise NotFoundException(detail="Portfolio not found")
    
    # Mark as inactive rather than deleting
    await portfolios_collection.update_one(
        {"_id": portfolio["_id"]},
        {
            "$set": {
                "is_active": False,
                "updated_at": get_current_time_ist()
            }
        }
    )
    
    return {"success": True, "message": "Portfolio marked as inactive"}

@router.post("/{portfolio_id}/rebalance", response_model=RebalanceRecommendation)
async def rebalance_portfolio(
    portfolio_id: str = Path(..., description="Portfolio ID"),
    tolerance_percentage: float = Query(5.0, description="Tolerance percentage for rebalancing"),
    token: str = Depends(oauth2_scheme)
):
    """
    Generate rebalancing recommendations for a portfolio
    """
    user_id = await get_current_user_id(token)
    
    # Check if portfolio exists and belongs to user
    portfolios_collection = await get_collection("portfolios")
    
    try:
        object_id = ObjectId(portfolio_id)
        portfolio = await portfolios_collection.find_one({
            "_id": object_id,
            "user_id": user_id
        })
    except Exception:
        portfolio = await portfolios_collection.find_one({
            "id": portfolio_id,
            "user_id": user_id
        })
    
    if not portfolio:
        raise NotFoundException(detail="Portfolio not found")
    
    portfolio_data = convert_mongo_document(portfolio)
    
    # Get current allocation
    holdings = portfolio_data.get("holdings", [])
    total_value = sum(holding.get("current_value", 0) for holding in holdings)
    
    current_allocation = {}
    for holding in holdings:
        asset_class = holding.get("asset_class", "unknown")
        if asset_class not in current_allocation:
            current_allocation[asset_class] = 0
        current_allocation[asset_class] += holding.get("current_value", 0) / total_value * 100 if total_value > 0 else 0
    
    # Get target allocation from portfolio
    target_allocation = portfolio_data.get("asset_allocation", {}).get("target_allocation", {})
    if not target_allocation:
        # If no target allocation defined, use default based on risk profile
        risk_profile = portfolio_data.get("risk_profile", RiskProfile.MODERATE)
        
        if risk_profile == RiskProfile.CONSERVATIVE:
            target_allocation = {"equity": 20, "debt": 70, "cash": 10}
        elif risk_profile == RiskProfile.MODERATE:
            target_allocation = {"equity": 40, "debt": 50, "cash": 5, "gold": 5}
        elif risk_profile == RiskProfile.BALANCED:
            target_allocation = {"equity": 60, "debt": 35, "alternative": 5}
        elif risk_profile == RiskProfile.GROWTH:
            target_allocation = {"equity": 75, "debt": 20, "alternative": 5}
        elif risk_profile == RiskProfile.AGGRESSIVE:
            target_allocation = {"equity": 85, "debt": 10, "alternative": 5}
    
    # Calculate needed adjustments
    recommendations = []
    expected_value_change = 0
    
    for asset_class, target_pct in target_allocation.items():
        current_pct = current_allocation.get(asset_class, 0)
        diff = target_pct - current_pct
        
        # Only recommend changes outside of tolerance range
        if abs(diff) >= tolerance_percentage:
            action = "BUY" if diff > 0 else "SELL"
            change_amount = abs(diff / 100 * total_value)
            expected_value_change += change_amount if action == "BUY" else 0
            
            recommendations.append({
                "asset_class": asset_class,
                "action": action,
                "current_percentage": current_pct,
                "target_percentage": target_pct,
                "difference": diff,
                "amount": change_amount
            })
    
    return RebalanceRecommendation(
        portfolio_id=portfolio_data["id"],
        current_allocation=current_allocation,
        target_allocation=target_allocation,
        recommendations=recommendations,
        expected_value_change=expected_value_change
    )

@router.get("/test-recommendations")
async def test_recommendations():
    """Simple test endpoint"""
    return {"message": "This is a test recommendations endpoint"}

logger.debug(f"Defined routes in portfolios router: {[route.path for route in router.routes]}")