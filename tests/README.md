# Testing Suite - مجموعة الاختبارات

## Overview

Professional testing tools for UAE-Sale system performance and load testing.

---

## Available Tests

### 1. Load Testing - اختبار الحمل
**File:** `load_test.py`

**Purpose:** Test system under normal-to-high load with multiple concurrent users.

**Usage:**
```bash
python tests/load_test.py
```

**What it tests:**
- Concurrent user sessions (10, 25, 50 users)
- Multiple endpoint requests
- Response times
- Success rates
- System stability

**Metrics:**
- Total requests
- Success/failure rates
- Response times (avg, min, max)
- Throughput (requests/second)

---

### 2. Stress Testing - اختبار الضغط
**File:** `stress_test.py`

**Purpose:** Find system breaking point by progressively increasing load.

**Usage:**
```bash
python tests/stress_test.py
```

**What it does:**
- Starts with 5 concurrent users
- Increases to 10, 20, 30, 50, 75, 100
- Stops when system starts failing
- Identifies maximum capacity

**Metrics:**
- Maximum concurrent users supported
- Performance degradation curve
- Breaking point identification
- Optimization recommendations

---

### 3. Performance Monitoring - مراقبة الأداء
**File:** `performance_monitor.py`

**Purpose:** Real-time monitoring of system performance.

**Usage:**
```bash
python tests/performance_monitor.py
```

**What it monitors:**
- CPU usage
- RAM usage
- Disk usage
- Response times
- Request success rate

**Duration options:**
- Quick test: 30 seconds
- Standard test: 60 seconds
- Extended test: 120 seconds

---

## Requirements

Install testing dependencies:

```bash
pip install requests psutil
```

---

## Before Testing

### 1. Start the Server
```bash
python app.py
```

### 2. Ensure Redis is Running (Optional)
```bash
redis-server
```

### 3. Have Test Users Ready
- admin / admin123
- owner / owner@2025!secure

---

## Interpreting Results

### Response Time
- **< 200ms:** ⭐⭐⭐⭐⭐ Excellent
- **200-500ms:** ⭐⭐⭐⭐ Good
- **500-1000ms:** ⭐⭐⭐ Average
- **> 1000ms:** ⭐⭐ Needs improvement

### Success Rate
- **> 95%:** ⭐⭐⭐⭐⭐ Excellent
- **90-95%:** ⭐⭐⭐⭐ Good
- **80-90%:** ⭐⭐⭐ Average
- **< 80%:** ⭐⭐ Problematic

### CPU Usage
- **< 50%:** ⭐⭐⭐⭐⭐ Excellent
- **50-70%:** ⭐⭐⭐⭐ Good
- **70-85%:** ⭐⭐⭐ High
- **> 85%:** ⭐⭐ Critical

---

## Expected Results

### Light Load (10 users)
- Response time: < 150ms
- CPU: < 30%
- RAM: < 500MB
- Success rate: 100%

### Medium Load (25 users)
- Response time: < 300ms
- CPU: < 50%
- RAM: < 800MB
- Success rate: > 95%

### Heavy Load (50 users)
- Response time: < 500ms
- CPU: < 70%
- RAM: < 1.2GB
- Success rate: > 90%

---

## Optimization Tips

### If Response Time is High
1. Enable Redis caching
2. Optimize database queries
3. Add database indexes
4. Use connection pooling

### If CPU is High
1. Reduce logging level
2. Optimize algorithms
3. Enable caching
4. Consider async processing

### If Memory is High
1. Check for memory leaks
2. Optimize data structures
3. Clear unused cache
4. Limit result set sizes

---

## Production Recommendations

Based on test results:

**For 10-20 concurrent users:**
- 2 CPU cores
- 2GB RAM
- Redis caching enabled

**For 50+ concurrent users:**
- 4 CPU cores
- 4GB RAM
- Redis caching + load balancer
- PostgreSQL instead of SQLite

**For 100+ concurrent users:**
- 8 CPU cores
- 8GB RAM
- Load balancer (multiple instances)
- PostgreSQL with replication
- CDN for static assets

---

## Notes

- These tests simulate real user behavior
- Results may vary based on hardware
- Run tests during low-traffic periods
- Always test on staging environment first

---

**Last Updated:** January 2025  
**Version:** 1.0.0

© 2025 Azad Smart Systems

