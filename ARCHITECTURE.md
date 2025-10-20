# System Architecture

## Overview

UAE-Sale is a modular, layered enterprise application built with Flask framework.

## Architecture Layers

```
┌─────────────────────────────────────────────────┐
│            Presentation Layer                    │
│  (Templates, Static Files, Forms)               │
└─────────────────────────────────────────────────┘
                      ↓
┌─────────────────────────────────────────────────┐
│            Application Layer                     │
│  (Routes/Blueprints, Controllers)               │
└─────────────────────────────────────────────────┘
                      ↓
┌─────────────────────────────────────────────────┐
│            Business Logic Layer                  │
│  (Services, AI Engines, Event Listeners)        │
└─────────────────────────────────────────────────┘
                      ↓
┌─────────────────────────────────────────────────┐
│            Data Access Layer                     │
│  (Models, SQLAlchemy ORM)                       │
└─────────────────────────────────────────────────┘
                      ↓
┌─────────────────────────────────────────────────┐
│            Database Layer                        │
│  (SQLite/PostgreSQL, Redis Cache)              │
└─────────────────────────────────────────────────┘
```

## Core Components

### 1. Web Framework
- **Flask 3.0:** Lightweight WSGI web application framework
- **Blueprints:** Modular route organization
- **Jinja2:** Template engine with RTL support

### 2. Database Layer
- **SQLAlchemy 2.0:** ORM with connection pooling
- **Flask-Migrate:** Database version control
- **Redis:** Caching and session storage

### 3. AI/ML Components
- **Neural Engine:** 10 neural network models
- **Semantic Matcher:** Intent recognition (35 intents)
- **Data Analyzer:** Real-time business intelligence
- **Reasoning Engine:** Logical inference system
- **Memory System:** Conversation context management

### 4. Security
- **Flask-Login:** User session management
- **bcrypt:** Password hashing
- **CSRF Protection:** Cross-site request forgery prevention
- **RBAC:** Role-based access control

### 5. Background Tasks
- **Celery:** Asynchronous task queue
- **Redis Broker:** Message broker for Celery

## Data Flow

### Request Lifecycle

```
User Request
    ↓
Flask App (app.py)
    ↓
Blueprint Routes (routes/*.py)
    ↓
Service Layer (services/*.py)
    ↓
Models (models/*.py)
    ↓
Database
    ↓
Event Listeners (models/events.py)
    ↓
AI Processing (ai_knowledge/*.py)
    ↓
Response
```

### AI Assistant Flow

```
User Message
    ↓
Semantic Matcher (intent detection)
    ↓
Intelligent Assistant (orchestration)
    ↓
┌─────────────────────────────────────┐
│  Neural Engine  │  Reasoning Engine  │
│  Data Analyzer  │  Memory System     │
└─────────────────────────────────────┘
    ↓
Context Engine (build response)
    ↓
External AI (Groq/Gemini) [optional]
    ↓
Final Response
```

## Module Dependencies

```
app.py
├── config.py
├── extensions.py
├── routes/
│   ├── auth.py
│   ├── sales.py
│   ├── customers.py
│   └── ... (12+ blueprints)
├── models/
│   ├── user.py
│   ├── customer.py
│   ├── sale.py
│   └── events.py (event listeners)
├── services/
│   ├── ai_service.py
│   ├── sale_service.py
│   └── ...
└── ai_knowledge/
    ├── intelligent_assistant.py
    ├── neural_engine.py
    ├── semantic_matcher.py
    └── ... (47 files)
```

## Database Schema

### Core Tables
- **users:** System users with RBAC
- **customers:** Client information
- **suppliers:** Vendor information
- **products:** Inventory items
- **sales:** Sales transactions
- **purchases:** Purchase orders
- **payments:** Payment records
- **cheques:** Check management
- **gl_accounts:** General ledger

### Relationships
- One-to-Many: Customer → Sales, Supplier → Purchases
- Many-to-Many: Sales ↔ Products (via sale_lines)
- One-to-One: User → Role

## Caching Strategy

### Redis Cache Layers
1. **Session Cache:** User sessions (TTL: 24h)
2. **Query Cache:** Frequent database queries (TTL: 5min)
3. **AI Cache:** Neural network predictions (TTL: 1h)
4. **Report Cache:** Generated reports (TTL: 15min)

## Performance Optimizations

1. **Database Indexing:** 15+ strategic indexes
2. **Connection Pooling:** pool_size=10, max_overflow=20
3. **Lazy Loading:** Relationships loaded on-demand
4. **Query Optimization:** Eager loading for common patterns
5. **Static Asset Compression:** Gzip for JS/CSS

## Scalability Considerations

### Horizontal Scaling
- Stateless application design
- Session data in Redis (shared across instances)
- Database connection pooling

### Vertical Scaling
- Efficient query patterns
- Caching at multiple layers
- Background task processing

## Deployment Architecture

### Production Setup
```
Internet
    ↓
Reverse Proxy (nginx/Apache)
    ↓
WSGI Server (Gunicorn)
    ↓
Flask Application
    ↓
Database (PostgreSQL) + Cache (Redis)
```

## Security Architecture

### Authentication Flow
1. User submits credentials
2. bcrypt password verification
3. Session creation (Flask-Login)
4. CSRF token generation
5. Role/permission check (RBAC)

### Data Protection
- **In Transit:** HTTPS (TLS 1.3)
- **At Rest:** Database encryption
- **Passwords:** bcrypt (12 rounds)
- **Sensitive Data:** AES-256 encryption

## Monitoring & Logging

### Logging Levels
- **INFO:** Regular operations
- **WARNING:** Potential issues
- **ERROR:** Application errors
- **CRITICAL:** System failures

### Monitored Metrics
- Response time
- Database query performance
- Cache hit rate
- AI model accuracy
- User activity

---

**Last Updated:** January 2025  
**Version:** 2.0.0

© 2025 Azad Smart Systems

