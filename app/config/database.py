import logging
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError

from app.config.settings import get_settings

# Get settings instance
settings = get_settings()

# Create a logger
logger = logging.getLogger(__name__)

class Database:
    client: AsyncIOMotorClient = None
    db = None

db = Database()

async def connect_to_mongo():
    """Connect to MongoDB Atlas"""
    logger.info("Connecting to MongoDB Atlas...")
    try:
        db.client = AsyncIOMotorClient(
            settings.MONGODB_URI,
            serverSelectionTimeoutMS=100000 # 5 seconds timeout
        )
        # Verify the connection is successful
        await db.client.admin.command('ismaster')
        db.db = db.client[settings.MONGODB_DB_NAME]
        logger.info("Connected to MongoDB Atlas")
    except (ConnectionFailure, ServerSelectionTimeoutError) as e:
        logger.error(f"Could not connect to MongoDB: {e}")
        raise

async def close_mongo_connection():
    """Close MongoDB connection"""
    logger.info("Closing MongoDB connection...")
    if db.client:
        db.client.close()
        logger.info("MongoDB connection closed")

async def get_database():
    """Get database instance"""
    if db.db is None:
        await connect_to_mongo()
    return db.db

async def health_check():
    """Perform a health check on the database connection"""
    try:
        if db.client is None:
            await connect_to_mongo()
        # Simple ping to verify connection is alive
        await db.client.admin.command('ping')
        return True
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return False

# Collection utility functions
async def get_collection(collection_name: str):
    """Get a specific collection from the database"""
    database = await get_database()
    return database[collection_name]

# Common database operations
async def insert_document(collection_name: str, document: dict):
    """Insert a single document into a collection"""
    collection = await get_collection(collection_name)
    result = await collection.insert_one(document)
    return result.inserted_id

async def find_document(collection_name: str, query: dict):
    """Find a single document in a collection"""
    collection = await get_collection(collection_name)
    return await collection.find_one(query)

async def find_documents(collection_name: str, query: dict, skip: int = 0, limit: int = 100):
    """Find multiple documents in a collection"""
    collection = await get_collection(collection_name)
    cursor = collection.find(query).skip(skip).limit(limit)
    return await cursor.to_list(length=limit)

async def update_document(collection_name: str, query: dict, update: dict):
    """Update a document in a collection"""
    collection = await get_collection(collection_name)
    result = await collection.update_one(query, {"$set": update})
    return result.modified_count