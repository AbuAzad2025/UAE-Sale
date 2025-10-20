# API Documentation

## Base URL

```
Production: https://uaesale-azad.pythonanywhere.com
Local: http://localhost:8080
```

## Authentication

All API endpoints require authentication via session cookies.

### Login
```http
POST /login
Content-Type: application/x-www-form-urlencoded

username=admin&password=admin123
```

## Core Endpoints

### Sales Management

#### Create Sale
```http
POST /sales/create
Content-Type: application/json

{
  "customer_id": 1,
  "sale_date": "2025-01-20",
  "items": [
    {
      "product_id": 1,
      "quantity": 5,
      "price": 100.00
    }
  ]
}
```

#### Get Sales List
```http
GET /sales/list?page=1&per_page=20
```

#### Get Sale Details
```http
GET /sales/view/<sale_id>
```

### Customer Management

#### Create Customer
```http
POST /customers/create
Content-Type: application/json

{
  "name": "Customer Name",
  "phone": "+970-xxx-xxx-xxx",
  "email": "customer@example.com",
  "customer_type": "regular"
}
```

#### Get Customer List
```http
GET /customers/list?search=name&customer_type=all
```

### Inventory

#### Get Stock Levels
```http
GET /products/inventory?warehouse_id=1
```

#### Update Stock
```http
POST /products/update-stock/<product_id>
Content-Type: application/json

{
  "quantity": 100,
  "warehouse_id": 1
}
```

### Reports

#### Sales Report
```http
GET /reports/sales?start_date=2025-01-01&end_date=2025-01-31
```

#### Inventory Report
```http
GET /reports/inventory?warehouse_id=1
```

#### Customer Balance
```http
GET /reports/receivables?customer_id=1
```

### AI Assistant

#### Chat with AI
```http
POST /ai/chat
Content-Type: application/json

{
  "message": "Analyze my sales this month",
  "context": {}
}

Response:
{
  "success": true,
  "response": "Your sales analysis...",
  "data": {}
}
```

## Response Formats

### Success Response
```json
{
  "success": true,
  "data": {},
  "message": "Operation successful"
}
```

### Error Response
```json
{
  "success": false,
  "error": "Error description",
  "code": 400
}
```

## Status Codes

- **200 OK:** Successful request
- **201 Created:** Resource created
- **400 Bad Request:** Invalid input
- **401 Unauthorized:** Authentication required
- **403 Forbidden:** Insufficient permissions
- **404 Not Found:** Resource not found
- **500 Internal Server Error:** Server error

## Rate Limiting

- **General:** 60 requests/minute
- **AI Endpoints:** 10 requests/minute
- **Auth Endpoints:** 5 requests/minute

## Webhooks (Future)

Webhook support for:
- New sales created
- Low stock alerts
- Payment received
- Customer activity

---

**Version:** 2.0.0  
**Last Updated:** January 2025

For detailed API integration, contact: rafideen.ahmadghannam@gmail.com

© 2025 Azad Smart Systems

