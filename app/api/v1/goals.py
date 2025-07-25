from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, status, Path, Query
from bson import ObjectId
import logging
import uuid

from app.config.database import get_collection
from app.core.security import oauth2_scheme, decode_access_token
from app.core.exceptions import NotFoundException, UnauthorizedException, BadRequestException
from app.schemas.goal import (
    GoalResponse,
    GoalSummaryResponse,
    GoalCreate,
    GoalUpdate,
    MilestoneCreate,
    MilestoneUpdate,
    ContributionCreate,
    GoalProjection
)
from app.models.goal import Goal, GoalStatus, GoalType, GoalPriority, ContributionFrequency
from app.utils.helpers import get_current_time_ist, convert_mongo_document, get_indian_timezone

# Configure logger
logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/goals",
    tags=["goals"],
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

@router.get("/", response_model=List[GoalSummaryResponse])
async def list_goals(
    token: str = Depends(oauth2_scheme),
    status: Optional[GoalStatus] = Query(None, description="Filter by goal status"),
    type: Optional[GoalType] = Query(None, description="Filter by goal type"),
    priority: Optional[GoalPriority] = Query(None, description="Filter by goal priority"),
    include_completed: bool = Query(False, description="Include completed goals")
):
    """
    List all financial goals for the current user
    
    - **status**: Filter by goal status
    - **type**: Filter by goal type
    - **priority**: Filter by goal priority
    - **include_completed**: Include completed goals (default: False)
    """
    logger.info("Getting goals list")
    
    user_id = await get_current_user_id(token)
    
    # Build filter query
    filter_query = {"user_id": user_id}
    
    # Apply filters if specified
    if status:
        filter_query["status"] = status
    
    if type:
        filter_query["goal_type"] = type
    
    if priority:
        filter_query["priority"] = priority
    
    # Exclude completed goals unless specifically requested
    if not include_completed:
        filter_query["status"] = {"$ne": GoalStatus.ACHIEVED}
    
    # Get goals from database
    goals_collection = await get_collection("goals")
    
    # Try with both ObjectId and string user_id
    try:
        object_id = ObjectId(user_id)
        goals = await goals_collection.find({"user_id": object_id}).to_list(length=100)
        
        # If no goals found with ObjectId, try with string ID
        if not goals:
            goals = await goals_collection.find({"user_id": user_id}).to_list(length=100)
    except Exception:
        # If conversion fails, use string ID directly
        goals = await goals_collection.find({"user_id": user_id}).to_list(length=100)
    
    # Convert to response model
    result = []
    for goal in goals:
        goal_data = convert_mongo_document(goal)
        
        # Build response summary
        goal_summary = {
            "id": goal_data["id"],
            "name": goal_data["name"],
            "goal_type": goal_data["goal_type"],
            "target_amount": goal_data["target_amount"],
            "current_amount": goal_data.get("current_amount", 0),
            "target_date": goal_data["target_date"],
            "completion_percentage": goal_data.get("completion_percentage", 0),
            "status": goal_data["status"],
            "priority": goal_data["priority"],
            "icon": goal_data.get("icon")
        }
        result.append(goal_summary)
    
    # Sort by priority and then by target date
    result.sort(key=lambda x: (
        {"high": 1, "medium": 2, "low": 3, "critical": 0}.get(x["priority"], 4),
        x["target_date"]
    ))
    
    logger.info(f"Returning {len(result)} goals for user {user_id}")
    return result

@router.get("/{goal_id}", response_model=GoalResponse)
async def get_goal(
    goal_id: str = Path(..., description="Goal ID"),
    token: str = Depends(oauth2_scheme)
):
    """
    Get detailed information about a specific financial goal
    """
    user_id = await get_current_user_id(token)
    
    # Get goal from database
    goals_collection = await get_collection("goals")
    
    # Try both string ID and MongoDB ObjectId
    goal = None
    
    try:
        # Try with ObjectId first
        object_goal_id = ObjectId(goal_id)
        goal = await goals_collection.find_one({
            "_id": object_goal_id,
            "user_id": user_id
        })
        
        # If not found, try with string ID
        if not goal:
            goal = await goals_collection.find_one({
                "id": goal_id,
                "user_id": user_id
            })
            
    except Exception as e:
        # If ObjectId conversion fails, try with string ID
        logger.error(f"Error converting goal ID to ObjectId: {str(e)}")
        goal = await goals_collection.find_one({
            "id": goal_id,
            "user_id": user_id
        })
    
    if not goal:
        logger.error(f"Goal {goal_id} not found for user {user_id}")
        raise NotFoundException(detail="Goal not found")
    
    # Get target date and current time
    target_date = goal["target_date"]
    now = get_current_time_ist()
    
    # Fix datetime subtraction by ensuring both dates are timezone-aware or naive
    # Either make target_date timezone-aware:
    if target_date.tzinfo is None:
        # Get IST timezone from helper function
        ist = get_indian_timezone()
        target_date = ist.localize(target_date)
    
    # Or alternatively, make both naive (less recommended):
    # now = now.replace(tzinfo=None)
    
    # Calculate remaining days (safe now that both dates have compatible timezones)
    days_remaining = (target_date - now).days
    
    goal_data = convert_mongo_document(goal)
    
    # Calculate next contribution date if applicable
    if goal_data.get("contribution_frequency") != ContributionFrequency.ONE_TIME:
        last_contribution = goal_data.get("last_contribution_date")
        frequency = goal_data.get("contribution_frequency")
        
        if last_contribution:
            if frequency == ContributionFrequency.DAILY:
                next_date = last_contribution + timedelta(days=1)
            elif frequency == ContributionFrequency.WEEKLY:
                next_date = last_contribution + timedelta(days=7)
            elif frequency == ContributionFrequency.MONTHLY:
                # Simple approximation for monthly
                next_date = last_contribution + timedelta(days=30)
            elif frequency == ContributionFrequency.QUARTERLY:
                next_date = last_contribution + timedelta(days=90)
            elif frequency == ContributionFrequency.HALF_YEARLY:
                next_date = last_contribution + timedelta(days=182)
            elif frequency == ContributionFrequency.YEARLY:
                next_date = last_contribution + timedelta(days=365)
            else:
                next_date = None
            
            goal_data["next_contribution_date"] = next_date
    
    logger.info(f"Retrieved goal {goal_id} for user {user_id}")
    return goal_data

@router.post("/", status_code=status.HTTP_201_CREATED, response_model=GoalResponse)
async def create_goal(
    goal_data: GoalCreate,
    token: str = Depends(oauth2_scheme)
):
    """
    Create a new financial goal
    """
    logger.info("Creating new goal")
    user_id = await get_current_user_id(token)
    
    # Verify user ID matches the requested user_id for security
    if user_id != goal_data.user_id:
        logger.error(f"User ID mismatch: {user_id} vs {goal_data.user_id}")
        raise UnauthorizedException(detail="User ID does not match authentication")
    
    # Create goal object
    current_time = get_current_time_ist()
    goal = Goal(
        user_id=user_id,
        name=goal_data.name,
        description=goal_data.description,
        goal_type=goal_data.goal_type,
        icon=goal_data.icon,
        target_amount=goal_data.target_amount,
        current_amount=goal_data.initial_amount,
        initial_amount=goal_data.initial_amount,
        target_date=goal_data.target_date,
        start_date=current_time,
        status=GoalStatus.NOT_STARTED if goal_data.initial_amount == 0 else GoalStatus.IN_PROGRESS,
        priority=goal_data.priority,
        contribution_frequency=goal_data.contribution_frequency,
        contribution_amount=goal_data.contribution_amount,
        return_rate=goal_data.return_rate,
        risk_profile=goal_data.risk_profile,
        portfolio_id=goal_data.portfolio_id,
        account_ids=goal_data.account_ids or [],
        created_at=current_time,
        updated_at=current_time
    )
    
    # Calculate completion percentage
    if goal.target_amount > 0:
        completion_percentage = (goal.initial_amount / goal.target_amount) * 100
        goal.completion_percentage = min(completion_percentage, 100.0)
    else:
        goal.completion_percentage = 0.0
    
    # Save goal to database
    goals_collection = await get_collection("goals")
    result = await goals_collection.insert_one(goal.dict())
    
    # Update user's goal IDs list
    users_collection = await get_collection("users")
    await users_collection.update_one(
        {"_id": ObjectId(user_id) if isinstance(user_id, str) else user_id},
        {"$push": {"goal_ids": str(result.inserted_id)}}
    )
    
    # If goal is linked to a portfolio, update portfolio
    if goal.portfolio_id:
        portfolios_collection = await get_collection("portfolios")
        await portfolios_collection.update_one(
            {"_id": ObjectId(goal.portfolio_id) if isinstance(goal.portfolio_id, str) else goal.portfolio_id},
            {"$push": {"goal_ids": str(result.inserted_id)}}
        )
    
    logger.info(f"Created goal {result.inserted_id} for user {user_id}")
    
    # Get created goal
    created_goal = await goals_collection.find_one({"_id": result.inserted_id})
    return convert_mongo_document(created_goal)

@router.put("/{goal_id}", response_model=GoalResponse)
async def update_goal(
    goal_data: GoalUpdate,
    goal_id: str = Path(..., description="Goal ID"),
    token: str = Depends(oauth2_scheme)
):
    """
    Update a financial goal's information or progress
    """
    logger.info(f"Updating goal {goal_id}")
    user_id = await get_current_user_id(token)
    
    # Check if goal exists and belongs to user
    goals_collection = await get_collection("goals")
    
    # Try both string ID and MongoDB ObjectId
    goal = None
    
    try:
        # Try with ObjectId first
        object_goal_id = ObjectId(goal_id)
        goal = await goals_collection.find_one({
            "_id": object_goal_id,
            "user_id": user_id
        })
        
        # If not found, try with string ID
        if not goal:
            goal = await goals_collection.find_one({
                "id": goal_id,
                "user_id": user_id
            })
            
    except Exception as e:
        # If ObjectId conversion fails, try with string ID
        logger.error(f"Error converting goal ID to ObjectId: {str(e)}")
        goal = await goals_collection.find_one({
            "id": goal_id,
            "user_id": user_id
        })
    
    if not goal:
        logger.error(f"Goal {goal_id} not found for user {user_id}")
        raise NotFoundException(detail="Goal not found")
    
    # Prepare update data
    update_data = {k: v for k, v in goal_data.dict(exclude_unset=True).items() if v is not None}
    update_data["updated_at"] = get_current_time_ist()
    
    # Special handling for current_amount to update completion percentage
    if "current_amount" in update_data:
        target_amount = goal.get("target_amount", 0)
        if target_amount > 0:
            completion_percentage = (update_data["current_amount"] / target_amount) * 100
            update_data["completion_percentage"] = min(completion_percentage, 100.0)
            
            # Update status based on completion
            if completion_percentage >= 100:
                update_data["status"] = GoalStatus.ACHIEVED
            elif update_data["current_amount"] == 0:
                update_data["status"] = GoalStatus.NOT_STARTED
            else:
                # FIX: Make all datetimes timezone-aware before subtraction
                current_time = get_current_time_ist()
                start_date = goal["start_date"]
                target_date = goal["target_date"]
                
                # Get IST timezone
                ist = get_indian_timezone()
                
                # Make start_date timezone-aware if it's not
                if start_date.tzinfo is None:
                    start_date = ist.localize(start_date)
                
                # Make target_date timezone-aware if it's not
                if target_date.tzinfo is None:
                    target_date = ist.localize(target_date)
                
                # Calculate days with compatible timezone information
                total_days = (target_date - start_date).days
                days_passed = (current_time - start_date).days
                
                if total_days > 0:
                    expected_completion = (days_passed / total_days) * 100
                    if completion_percentage >= expected_completion:
                        update_data["status"] = GoalStatus.AHEAD_OF_SCHEDULE
                    else:
                        update_data["status"] = GoalStatus.BEHIND_SCHEDULE
                else:
                    update_data["status"] = GoalStatus.IN_PROGRESS
    
    # Handle portfolio association changes
    if "portfolio_id" in update_data and update_data["portfolio_id"] != goal.get("portfolio_id"):
        portfolios_collection = await get_collection("portfolios")
        
        # Remove from old portfolio
        if goal.get("portfolio_id"):
            await portfolios_collection.update_one(
                {"_id": ObjectId(goal["portfolio_id"]) if isinstance(goal["portfolio_id"], str) else goal["portfolio_id"]},
                {"$pull": {"goal_ids": goal_id}}
            )
        
        # Add to new portfolio
        if update_data["portfolio_id"]:
            await portfolios_collection.update_one(
                {"_id": ObjectId(update_data["portfolio_id"]) if isinstance(update_data["portfolio_id"], str) else update_data["portfolio_id"]},
                {"$push": {"goal_ids": goal_id}}
            )
    
    # Update goal
    await goals_collection.update_one(
        {"_id": goal["_id"]},
        {"$set": update_data}
    )
    
    logger.info(f"Updated goal {goal_id} for user {user_id}")
    
    # Get updated goal
    updated_goal = await goals_collection.find_one({"_id": goal["_id"]})
    return convert_mongo_document(updated_goal)

@router.delete("/{goal_id}", status_code=status.HTTP_200_OK)
async def delete_goal(
    goal_id: str = Path(..., description="Goal ID"),
    token: str = Depends(oauth2_scheme)
):
    """
    Delete a financial goal
    """
    logger.info(f"Deleting goal {goal_id}")
    user_id = await get_current_user_id(token)
    
    # Check if goal exists and belongs to user
    goals_collection = await get_collection("goals")
    
    # Try both string ID and MongoDB ObjectId
    goal = None
    
    try:
        # Try with ObjectId first
        object_goal_id = ObjectId(goal_id)
        goal = await goals_collection.find_one({
            "_id": object_goal_id,
            "user_id": user_id
        })
        
        # If not found, try with string ID
        if not goal:
            goal = await goals_collection.find_one({
                "id": goal_id,
                "user_id": user_id
            })
            
    except Exception as e:
        # If ObjectId conversion fails, try with string ID
        logger.error(f"Error converting goal ID to ObjectId: {str(e)}")
        goal = await goals_collection.find_one({
            "id": goal_id,
            "user_id": user_id
        })
    
    if not goal:
        logger.error(f"Goal {goal_id} not found for user {user_id}")
        raise NotFoundException(detail="Goal not found")
    
    # Remove goal from portfolio if linked
    if goal.get("portfolio_id"):
        portfolios_collection = await get_collection("portfolios")
        await portfolios_collection.update_one(
            {"_id": ObjectId(goal["portfolio_id"]) if isinstance(goal["portfolio_id"], str) else goal["portfolio_id"]},
            {"$pull": {"goal_ids": goal_id}}
        )
    
    # Remove goal from user's goal list
    users_collection = await get_collection("users")
    await users_collection.update_one(
        {"_id": ObjectId(user_id) if isinstance(user_id, str) else user_id},
        {"$pull": {"goal_ids": goal_id}}
    )
    
    # Delete goal
    await goals_collection.delete_one({"_id": goal["_id"]})
    
    logger.info(f"Deleted goal {goal_id} for user {user_id}")
    
    return {"success": True, "message": "Goal deleted successfully"}

@router.post("/{goal_id}/contributions", status_code=status.HTTP_200_OK, response_model=GoalResponse)
async def add_contribution(
    contribution_data: ContributionCreate,
    token: str = Depends(oauth2_scheme)
):
    """
    Add a contribution to a financial goal
    """
    logger.info(f"Adding contribution to goal {contribution_data.goal_id}")
    user_id = await get_current_user_id(token)
    
    # Check if goal exists and belongs to user
    goals_collection = await get_collection("goals")
    
    # Try both string ID and MongoDB ObjectId
    goal = None
    goal_id = contribution_data.goal_id
    
    try:
        # Try with ObjectId first
        object_goal_id = ObjectId(goal_id)
        goal = await goals_collection.find_one({
            "_id": object_goal_id,
            "user_id": user_id
        })
        
        # If not found, try with string ID
        if not goal:
            goal = await goals_collection.find_one({
                "id": goal_id,
                "user_id": user_id
            })
            
    except Exception as e:
        # If ObjectId conversion fails, try with string ID
        logger.error(f"Error converting goal ID to ObjectId: {str(e)}")
        goal = await goals_collection.find_one({
            "id": goal_id,
            "user_id": user_id
        })
    
    if not goal:
        logger.error(f"Goal {goal_id} not found for user {user_id}")
        raise NotFoundException(detail="Goal not found")
    
    # Create contribution record
    current_time = get_current_time_ist()
    contribution = {
        "amount": contribution_data.amount,
        "date": contribution_data.date or current_time,
        "source_account_id": contribution_data.source_account_id,
        "notes": contribution_data.notes
    }
    
    # Update goal with contribution
    new_current_amount = goal.get("current_amount", 0) + contribution_data.amount
    target_amount = goal.get("target_amount", 0)
    
    # Calculate completion percentage
    completion_percentage = 0
    if target_amount > 0:
        completion_percentage = (new_current_amount / target_amount) * 100
        completion_percentage = min(completion_percentage, 100.0)
    
    # Determine new status
    new_status = goal.get("status")
    if completion_percentage >= 100:
        new_status = GoalStatus.ACHIEVED
    elif new_current_amount > 0:
        # FIX: Make start_date timezone-aware before subtraction
        start_date = goal["start_date"]
        if start_date.tzinfo is None:
            ist = get_indian_timezone()
            start_date = ist.localize(start_date)
        
        # Fix target_date timezone
        target_date = goal["target_date"]
        if target_date.tzinfo is None:
            ist = get_indian_timezone()
            target_date = ist.localize(target_date)
            
        # Check if ahead or behind schedule
        total_days = (target_date - start_date).days
        days_passed = (current_time - start_date).days
        
        if total_days > 0:
            expected_completion = (days_passed / total_days) * 100
            if completion_percentage >= expected_completion:
                new_status = GoalStatus.AHEAD_OF_SCHEDULE
            else:
                new_status = GoalStatus.BEHIND_SCHEDULE
        else:
            new_status = GoalStatus.IN_PROGRESS
    
    # Update goal
    await goals_collection.update_one(
        {"_id": goal["_id"]},
        {
            "$push": {"contributions": contribution},
            "$set": {
                "current_amount": new_current_amount,
                "completion_percentage": completion_percentage,
                "status": new_status,
                "last_contribution_date": current_time,
                "updated_at": current_time
            }
        }
    )
    
    logger.info(f"Added contribution of {contribution_data.amount} to goal {goal_id}")
    
    # Get updated goal
    updated_goal = await goals_collection.find_one({"_id": goal["_id"]})
    return convert_mongo_document(updated_goal)

@router.post("/{goal_id}/milestones", status_code=status.HTTP_201_CREATED)
async def add_milestone(
    milestone_data: MilestoneCreate,
    goal_id: str = Path(..., description="Goal ID"),
    token: str = Depends(oauth2_scheme)
):
    """
    Add a milestone to a financial goal
    """
    logger.info(f"Adding milestone to goal {goal_id}")
    user_id = await get_current_user_id(token)
    
    # Check if goal exists and belongs to user
    goals_collection = await get_collection("goals")
    
    # Try both string ID and MongoDB ObjectId
    goal = None
    
    try:
        # Try with ObjectId first
        object_goal_id = ObjectId(goal_id)
        goal = await goals_collection.find_one({
            "_id": object_goal_id,
            "user_id": user_id
        })
        
        # If not found, try with string ID
        if not goal:
            goal = await goals_collection.find_one({
                "id": goal_id,
                "user_id": user_id
            })
            
    except Exception as e:
        # If ObjectId conversion fails, try with string ID
        logger.error(f"Error converting goal ID to ObjectId: {str(e)}")
        goal = await goals_collection.find_one({
            "id": goal_id,
            "user_id": user_id
        })
    
    if not goal:
        logger.error(f"Goal {goal_id} not found for user {user_id}")
        raise NotFoundException(detail="Goal not found")
    
    # Validate milestone
    if milestone_data.target_date > goal["target_date"]:
        logger.error(f"Milestone target date {milestone_data.target_date} is after goal target date {goal['target_date']}")
        raise BadRequestException(detail="Milestone target date cannot be after goal target date")
    
    if milestone_data.target_amount > goal["target_amount"]:
        logger.error(f"Milestone target amount {milestone_data.target_amount} exceeds goal target amount {goal['target_amount']}")
        raise BadRequestException(detail="Milestone target amount cannot exceed goal target amount")
    
    # Create milestone as a plain dictionary (avoids serialization issues)
    milestone_id = str(uuid.uuid4())
    milestone = {
        "id": milestone_id,
        "name": milestone_data.name,
        "target_date": milestone_data.target_date,
        "target_amount": milestone_data.target_amount,
        "description": milestone_data.description,
        "is_achieved": False,
        "achieved_date": None
    }
    
    # Update goal
    await goals_collection.update_one(
        {"_id": goal["_id"]},
        {
            "$push": {"milestones": milestone},
            "$set": {"updated_at": get_current_time_ist()}
        }
    )
    
    logger.info(f"Added milestone '{milestone_data.name}' to goal {goal_id}")
    
    # Return just the created milestone to avoid ObjectId serialization issues
    return {
        "id": milestone_id,
        "goal_id": goal_id,
        "name": milestone_data.name,
        "target_date": milestone_data.target_date,
        "target_amount": milestone_data.target_amount,
        "description": milestone_data.description,
        "is_achieved": False,
        "achieved_date": None
    }

@router.get("/{goal_id}/projection", response_model=GoalProjection)
async def get_goal_projection(
    goal_id: str = Path(..., description="Goal ID"),
    token: str = Depends(oauth2_scheme)
):
    """
    Get the projection of how a goal will progress over time
    """
    logger.info(f"Calculating projection for goal {goal_id}")
    user_id = await get_current_user_id(token)
    
    # Fetch the goal
    goals_collection = await get_collection("goals")
    
    # Try both string ID and MongoDB ObjectId
    goal = None
    
    try:
        # Try with ObjectId first
        object_goal_id = ObjectId(goal_id)
        goal = await goals_collection.find_one({
            "_id": object_goal_id,
            "user_id": user_id
        })
        
        # If not found, try with string ID
        if not goal:
            goal = await goals_collection.find_one({
                "id": goal_id,
                "user_id": user_id
            })
            
    except Exception as e:
        # If ObjectId conversion fails, try with string ID
        logger.error(f"Error converting goal ID to ObjectId: {str(e)}")
        goal = await goals_collection.find_one({
            "id": goal_id,
            "user_id": user_id
        })
    
    if not goal:
        logger.error(f"Goal {goal_id} not found for user {user_id}")
        raise NotFoundException(detail="Goal not found")
    
    # Make dates timezone-aware for calculations
    ist = get_indian_timezone()
    start_date = goal.get("start_date", get_current_time_ist())
    target_date = goal.get("target_date")
    
    # Make both dates timezone-aware
    if start_date.tzinfo is None:
        start_date = ist.localize(start_date)
    if target_date.tzinfo is None:
        target_date = ist.localize(target_date)
    
    current_amount = goal.get("current_amount", 0)
    target_amount = goal.get("target_amount", 0)
    contribution_amount = goal.get("contribution_amount", 0)
    contribution_frequency = goal.get("contribution_frequency", ContributionFrequency.MONTHLY)
    return_rate = goal.get("return_rate", 8.0) / 100  # Convert to decimal
    
    # Calculate number of months until target
    months_total = ((target_date.year - start_date.year) * 12 + 
                   target_date.month - start_date.month)
    
    # FIX: Create months list explicitly to include in response
    months = list(range(0, months_total + 1))
    projected_amounts = [current_amount]
    target_line = [0]
    
    # Linear target line
    if months_total > 0:
        monthly_target_increment = target_amount / months_total
        target_line = [min(i * monthly_target_increment, target_amount) for i in range(months_total + 1)]
    
    # Calculate projected growth with compound interest
    for i in range(1, months_total + 1):
        prev_amount = projected_amounts[-1]
        
        # Add contribution based on frequency
        if contribution_frequency == ContributionFrequency.MONTHLY:
            contribution = contribution_amount
        elif contribution_frequency == ContributionFrequency.QUARTERLY:
            contribution = contribution_amount if i % 3 == 0 else 0
        elif contribution_frequency == ContributionFrequency.HALF_YEARLY:
            contribution = contribution_amount if i % 6 == 0 else 0
        elif contribution_frequency == ContributionFrequency.YEARLY:
            contribution = contribution_amount if i % 12 == 0 else 0
        else:
            contribution = 0
        
        # Apply monthly growth rate (annual rate / 12)
        monthly_return = prev_amount * (return_rate / 12)
        new_amount = prev_amount + monthly_return + contribution
        projected_amounts.append(new_amount)
    
    # Map milestones to projection timeline
    milestone_points = []
    for milestone in goal.get("milestones", []):
        milestone_date = milestone.get("target_date")
        if milestone_date:
            # Make milestone dates timezone-aware
            if milestone_date.tzinfo is None:
                milestone_date = ist.localize(milestone_date)
                
            months_from_start = ((milestone_date.year - start_date.year) * 12 + 
                               milestone_date.month - start_date.month)
            if 0 <= months_from_start <= months_total:
                milestone_points.append({
                    "month": months_from_start,
                    "target_amount": milestone.get("target_amount"),
                    "name": milestone.get("name"),
                    "is_achieved": milestone.get("is_achieved", False)
                })
    
    # Return projection data
    # FIX: Include 'months' field in the response
    return {
        "goal_id": goal_id,
        "months": months,
        "projected_amounts": projected_amounts,
        "target_line": target_line,
        "milestone_points": milestone_points
    }
