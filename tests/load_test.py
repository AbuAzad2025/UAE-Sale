"""
Load Testing for UAE-Sale System
اختبار تحمل الضغط للنظام
"""

import time
import random
import threading
from datetime import datetime
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

# Configuration
BASE_URL = "http://localhost:8080"
MAX_USERS = 50  # عدد المستخدمين المتزامنين
REQUESTS_PER_USER = 10  # عدد الطلبات لكل مستخدم
TIMEOUT = 5  # ثواني

# Test credentials
TEST_USERS = [
    {"username": "admin", "password": "admin123"},
    {"username": "owner", "password": "owner@2025!secure"},
]

class LoadTester:
    def __init__(self, base_url=BASE_URL):
        self.base_url = base_url
        self.results = {
            'total_requests': 0,
            'successful': 0,
            'failed': 0,
            'avg_response_time': 0,
            'min_response_time': float('inf'),
            'max_response_time': 0,
            'errors': []
        }
        self.response_times = []
    
    def create_session(self, username, password):
        """إنشاء جلسة مستخدم"""
        session = requests.Session()
        try:
            response = session.post(
                f"{self.base_url}/login",
                data={'username': username, 'password': password},
                timeout=TIMEOUT
            )
            if response.status_code == 200:
                return session
        except Exception as e:
            print(f"Login failed: {e}")
        return None
    
    def test_endpoint(self, session, endpoint, method='GET', data=None):
        """اختبار endpoint محدد"""
        start_time = time.time()
        try:
            if method == 'GET':
                response = session.get(f"{self.base_url}{endpoint}", timeout=TIMEOUT)
            else:
                response = session.post(f"{self.base_url}{endpoint}", json=data, timeout=TIMEOUT)
            
            response_time = (time.time() - start_time) * 1000  # بالميلي ثانية
            
            self.response_times.append(response_time)
            self.results['total_requests'] += 1
            
            if response.status_code == 200:
                self.results['successful'] += 1
            else:
                self.results['failed'] += 1
                self.results['errors'].append(f"{endpoint}: {response.status_code}")
            
            self.results['min_response_time'] = min(self.results['min_response_time'], response_time)
            self.results['max_response_time'] = max(self.results['max_response_time'], response_time)
            
            return response_time
        
        except Exception as e:
            self.results['total_requests'] += 1
            self.results['failed'] += 1
            self.results['errors'].append(f"{endpoint}: {str(e)}")
            return None
    
    def simulate_user(self, user_id):
        """محاكاة سلوك مستخدم واحد"""
        user_creds = random.choice(TEST_USERS)
        session = self.create_session(user_creds['username'], user_creds['password'])
        
        if not session:
            return
        
        # Endpoints to test
        endpoints = [
            '/dashboard',
            '/customers/list',
            '/products/list',
            '/sales/list',
            '/reports/index',
        ]
        
        for _ in range(REQUESTS_PER_USER):
            endpoint = random.choice(endpoints)
            self.test_endpoint(session, endpoint)
            time.sleep(random.uniform(0.1, 0.5))  # تأخير طبيعي
    
    def run_load_test(self, num_users=MAX_USERS):
        """تشغيل اختبار الضغط"""
        print(f"\n{'='*60}")
        print(f"  Load Testing - اختبار تحمل الضغط")
        print(f"{'='*60}")
        print(f"Base URL: {self.base_url}")
        print(f"Concurrent Users: {num_users}")
        print(f"Requests per User: {REQUESTS_PER_USER}")
        print(f"Total Requests: {num_users * REQUESTS_PER_USER}")
        print(f"{'='*60}\n")
        
        start_time = time.time()
        
        with ThreadPoolExecutor(max_workers=num_users) as executor:
            futures = [executor.submit(self.simulate_user, i) for i in range(num_users)]
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    print(f"Error in thread: {e}")
        
        duration = time.time() - start_time
        
        # حساب المتوسطات
        if self.response_times:
            self.results['avg_response_time'] = sum(self.response_times) / len(self.response_times)
        
        self.print_results(duration)
    
    def print_results(self, duration):
        """طباعة النتائج"""
        print(f"\n{'='*60}")
        print(f"  Test Results - نتائج الاختبار")
        print(f"{'='*60}")
        print(f"Duration: {duration:.2f} seconds")
        print(f"Total Requests: {self.results['total_requests']}")
        print(f"Successful: {self.results['successful']} ({self.results['successful']/self.results['total_requests']*100:.1f}%)")
        print(f"Failed: {self.results['failed']} ({self.results['failed']/self.results['total_requests']*100:.1f}%)")
        print(f"\nResponse Times:")
        print(f"  Average: {self.results['avg_response_time']:.2f} ms")
        print(f"  Min: {self.results['min_response_time']:.2f} ms")
        print(f"  Max: {self.results['max_response_time']:.2f} ms")
        print(f"\nThroughput: {self.results['total_requests']/duration:.2f} requests/second")
        
        if self.results['errors']:
            print(f"\n⚠️  Errors ({len(self.results['errors'])}):")
            for error in self.results['errors'][:10]:  # أول 10 أخطاء
                print(f"  - {error}")
        
        # التقييم
        print(f"\n{'='*60}")
        print(f"  Performance Rating - تقييم الأداء")
        print(f"{'='*60}")
        
        avg_time = self.results['avg_response_time']
        success_rate = self.results['successful']/self.results['total_requests']*100
        
        if avg_time < 200 and success_rate > 95:
            rating = "⭐⭐⭐⭐⭐ Excellent - ممتاز"
        elif avg_time < 500 and success_rate > 90:
            rating = "⭐⭐⭐⭐ Good - جيد"
        elif avg_time < 1000 and success_rate > 80:
            rating = "⭐⭐⭐ Average - متوسط"
        else:
            rating = "⭐⭐ Needs Improvement - يحتاج تحسين"
        
        print(f"Rating: {rating}")
        print(f"{'='*60}\n")


if __name__ == "__main__":
    print("\n🚀 UAE-Sale Load Testing Tool")
    print("📊 تأكد من تشغيل السيرفر على: http://localhost:8080\n")
    
    input("اضغط Enter للبدء...")
    
    tester = LoadTester()
    
    # Test levels
    tests = [
        (10, "Light Load - حمل خفيف"),
        (25, "Medium Load - حمل متوسط"),
        (50, "Heavy Load - حمل ثقيل"),
    ]
    
    for num_users, description in tests:
        print(f"\n\n{'#'*60}")
        print(f"  {description} ({num_users} users)")
        print(f"{'#'*60}")
        
        tester = LoadTester()
        tester.run_load_test(num_users)
        
        time.sleep(2)  # راحة بين الاختبارات
    
    print("\n✅ All tests completed!")
    print("© 2025 Azad Smart Systems\n")

