Absolutely! Here's a detailed and structured Markdown documentation for testing the **AI Coach API Endpoints** using Postman:

---

# 🤖 Postman Testing Guide: AI Coach API Endpoints

## 🔐 Authentication Reminder

Ensure you’ve obtained your `access_token` via the login endpoint:

```
POST http://localhost:8000/api/v1/auth/login
```

Use the token in the header for all requests:

```
Authorization: Bearer YOUR_ACCESS_TOKEN
Content-Type: application/json
```

---

## 🧠 1. Chat with AI

Initiate or continue a conversation with the AI Coach.

### 🔸 Endpoint

**POST** `http://localhost:8000/api/v1/ai-coach/chat`

### 📝 Request Body

```json
{
  "user_id": "6852a8097dc3f22307e1ddd9",
  "question": "How can I reduce my monthly expenses?",
  "session_id": null
}
```

- `user_id`: Your authenticated user ID
- `question`: The query or message for the AI Coach
- `session_id`: Leave `null` to start a new session, or provide an existing session ID to continue

### ✅ Expected Response (Example)

```json
{
  "session_id": "9a12b8097dc3f22307e1ddee",
  "response": "To reduce your monthly expenses, start by tracking your spending, identifying non-essential costs, and setting a realistic budget. Consider using budgeting apps and automating savings.",
  "timestamp": "2025-06-30T12:15:00Z"
}
```

---

## 📊 2. Get Financial Insights

Retrieve personalized insights based on your financial behavior.

### 🔸 Endpoint

**GET** `http://localhost:8000/api/v1/ai-coach/insights`

### 🔍 Query Parameters

| Parameter  | Description                              |
|------------|------------------------------------------|
| timeframe  | "week", "month", "quarter", or "year"    |

### 🧪 Example Request

```
GET http://localhost:8000/api/v1/ai-coach/insights?timeframe=week
```

### ✅ Expected Response (Example)

```json
{
  "timeframe": "week",
  "insights": [
    {
      "title": "Spending Spike on Weekends",
      "description": "Your weekend spending increased by 20% compared to weekdays. Consider planning ahead to avoid impulse purchases."
    },
    {
      "title": "Consistent Savings",
      "description": "You saved ₹5,000 this week, maintaining a consistent savings habit. Great job!"
    }
  ]
}
```

---

## 💸 3. Analyze Spending

Analyze your spending patterns over a specific period or category.

### 🔸 Endpoint

**POST** `http://localhost:8000/api/v1/ai-coach/analyze-spending`

### 🔍 Query Parameters

| Parameter   | Description                                      |
|-------------|--------------------------------------------------|
| start_date  | Start date in ISO format (e.g., `2025-05-01T00:00:00`) |
| end_date    | End date in ISO format (e.g., `2025-05-30T23:59:59`)   |
| category    | Spending category (e.g., `food_dining`, `shopping`)   |

### 🧪 Example Request

```
POST http://localhost:8000/api/v1/ai-coach/analyze-spending?start_date=2025-05-01T00:00:00&end_date=2025-05-30T23:59:59&category=food_dining
```

### ✅ Expected Response (Example)

```json
{
  "category": "food_dining",
  "total_spent": 8200,
  "average_daily_spend": 273.33,
  "recommendations": [
    "Consider meal prepping to reduce dining out expenses.",
    "Track food delivery orders and set a monthly limit."
  ]
}
```

---

## 🧪 Testing Tips

- ✅ Replace placeholder IDs (`user_id`, `account_id`, `instrument_id`) with real values from your database.
- 🔁 If you receive a `401 Unauthorized`, your token may have expired—re-authenticate.
- 🧾 Always set `Content-Type: application/json` for POST requests.
- 🧠 Use the AI Coach to simulate real-world financial conversations and planning.

---

## 🔄 Sample Workflow

1. 🔍 Get investment recommendations based on your risk profile and amount.
2. 💼 Execute an investment using the recommended instruments.
3. 📈 Check performance metrics for your portfolio.
4. 🧠 Ask the AI Coach about your investment strategy.
5. 📊 Retrieve financial insights to understand your habits.
6. 💸 Analyze your spending patterns for better budgeting.

> This workflow simulates a complete user journey through the investment and AI coaching features.

---

Let me know if you'd like this bundled into a downloadable `.md` file or combined with the Investment API documentation!
