"""
Stress Testing - اختبار الضغط الشديد
يزيد العمليات تدريجياً حتى يجد نقطة الانهيار
"""

import time
import requests
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

BASE_URL = "http://localhost:8080"

class StressTester:
    def __init__(self):
        self.results = []
    
    def test_concurrent_requests(self, num_requests):
        """اختبار عدد محدد من الطلبات المتزامنة"""
        successful = 0
        failed = 0
        response_times = []
        
        def single_request():
            try:
                start = time.time()
                response = requests.get(f"{BASE_URL}/dashboard", timeout=10)
                response_time = (time.time() - start) * 1000
                return (response.status_code == 200, response_time)
            except:
                return (False, 0)
        
        start_time = time.time()
        
        with ThreadPoolExecutor(max_workers=num_requests) as executor:
            futures = [executor.submit(single_request) for _ in range(num_requests)]
            for future in futures:
                success, response_time = future.result()
                if success:
                    successful += 1
                    response_times.append(response_time)
                else:
                    failed += 1
        
        duration = time.time() - start_time
        avg_response = sum(response_times) / len(response_times) if response_times else 0
        
        return {
            'concurrent_users': num_requests,
            'successful': successful,
            'failed': failed,
            'avg_response_time': avg_response,
            'duration': duration,
            'throughput': num_requests / duration
        }
    
    def run_progressive_test(self):
        """اختبار تصاعدي - يزيد الضغط تدريجياً"""
        print(f"\n{'='*70}")
        print(f"  Progressive Stress Test - اختبار الضغط التصاعدي")
        print(f"{'='*70}\n")
        
        levels = [5, 10, 20, 30, 50, 75, 100]
        
        print(f"{'Users':<8} | {'Success':<10} | {'Failed':<8} | {'Avg Time (ms)':<15} | {'Throughput':<12}")
        print(f"{'-'*70}")
        
        for num_users in levels:
            result = self.test_concurrent_requests(num_users)
            self.results.append(result)
            
            print(f"{num_users:<8} | "
                  f"{result['successful']:<10} | "
                  f"{result['failed']:<8} | "
                  f"{result['avg_response_time']:>13.2f} | "
                  f"{result['throughput']:>10.2f} req/s")
            
            # توقف إذا بدأ النظام يفشل
            if result['failed'] / num_users > 0.5:  # أكثر من 50% فشل
                print(f"\n⚠️  System capacity reached at {num_users} concurrent users")
                break
            
            time.sleep(2)  # راحة بين المستويات
        
        self.print_analysis()
    
    def print_analysis(self):
        """تحليل النتائج"""
        print(f"\n{'='*70}")
        print(f"  Analysis - التحليل")
        print(f"{'='*70}")
        
        if not self.results:
            return
        
        # إيجاد أفضل أداء
        best = min(self.results, key=lambda x: x['avg_response_time'])
        print(f"Best Performance: {best['concurrent_users']} users @ {best['avg_response_time']:.2f} ms")
        
        # إيجاد الحد الأقصى
        max_successful = max(self.results, key=lambda x: x['successful'])
        print(f"Max Capacity: {max_successful['concurrent_users']} users")
        
        # التوصيات
        print(f"\n{'='*70}")
        print(f"  Recommendations - التوصيات")
        print(f"{'='*70}")
        
        avg_time = sum(r['avg_response_time'] for r in self.results) / len(self.results)
        
        if avg_time < 300:
            print("✅ النظام يتحمل الضغط بشكل ممتاز")
            print("   - يمكن خدمة 50+ مستخدم متزامن")
            print("   - الأداء مستقر")
        elif avg_time < 800:
            print("⚠️  الأداء جيد لكن يمكن تحسينه")
            print("   - زيادة Redis caching")
            print("   - تحسين database queries")
            print("   - Connection pooling optimization")
        else:
            print("❌ النظام يحتاج تحسينات")
            print("   - زيادة server resources")
            print("   - تفعيل load balancing")
            print("   - database optimization ضروري")
        
        print(f"{'='*70}\n")


if __name__ == "__main__":
    print("\n🔥 UAE-Sale Stress Testing Tool")
    print("⚠️  تأكد من تشغيل السيرفر على: http://localhost:8080")
    print("⚠️  هذا الاختبار سيضع ضغط كبير على النظام!\n")
    
    confirm = input("هل تريد المتابعة؟ (yes/no): ").strip().lower()
    
    if confirm in ['yes', 'y', 'نعم']:
        tester = StressTester()
        tester.run_progressive_test()
        print("\n✅ Stress testing complete!")
    else:
        print("\n❌ تم الإلغاء")
    
    print("© 2025 Azad Smart Systems\n")

