"""
Real-time Performance Monitor
مراقب الأداء الحي للنظام
"""

import time
import psutil
import requests
from datetime import datetime

BASE_URL = "http://localhost:8080"

class PerformanceMonitor:
    def __init__(self):
        self.monitoring = True
    
    def get_system_metrics(self):
        """قياس موارد النظام"""
        return {
            'cpu': psutil.cpu_percent(interval=1),
            'memory': psutil.virtual_memory().percent,
            'disk': psutil.disk_usage('/').percent,
        }
    
    def test_response_time(self, endpoint='/dashboard'):
        """قياس وقت الاستجابة"""
        try:
            start = time.time()
            response = requests.get(f"{BASE_URL}{endpoint}", timeout=5)
            response_time = (time.time() - start) * 1000
            return {
                'status': response.status_code,
                'time': response_time,
                'success': response.status_code == 200
            }
        except Exception as e:
            return {
                'status': 0,
                'time': 0,
                'success': False,
                'error': str(e)
            }
    
    def monitor(self, duration=60):
        """مراقبة مستمرة لمدة محددة"""
        print(f"\n{'='*70}")
        print(f"  Real-time Performance Monitoring - المراقبة الحية للأداء")
        print(f"{'='*70}")
        print(f"Duration: {duration} seconds")
        print(f"Base URL: {BASE_URL}")
        print(f"{'='*70}\n")
        
        print(f"{'Time':<10} | {'CPU%':<6} | {'RAM%':<6} | {'Response (ms)':<15} | {'Status':<8}")
        print(f"{'-'*70}")
        
        start_time = time.time()
        metrics_history = []
        
        while time.time() - start_time < duration:
            # System metrics
            sys_metrics = self.get_system_metrics()
            
            # Response time
            response = self.test_response_time()
            
            # Record
            metrics_history.append({
                'timestamp': datetime.now(),
                'cpu': sys_metrics['cpu'],
                'memory': sys_metrics['memory'],
                'response_time': response['time'],
                'status': response['status']
            })
            
            # Display
            current_time = datetime.now().strftime("%H:%M:%S")
            status = "✓ OK" if response['success'] else "✗ FAIL"
            
            print(f"{current_time:<10} | {sys_metrics['cpu']:>5.1f}% | "
                  f"{sys_metrics['memory']:>5.1f}% | {response['time']:>13.2f} | {status:<8}")
            
            time.sleep(2)  # كل ثانيتين
        
        self.print_summary(metrics_history)
    
    def print_summary(self, history):
        """ملخص النتائج"""
        if not history:
            return
        
        avg_cpu = sum(m['cpu'] for m in history) / len(history)
        avg_memory = sum(m['memory'] for m in history) / len(history)
        avg_response = sum(m['response_time'] for m in history) / len(history)
        
        successful = sum(1 for m in history if m['status'] == 200)
        
        print(f"\n{'='*70}")
        print(f"  Summary - الملخص")
        print(f"{'='*70}")
        print(f"Total Samples: {len(history)}")
        print(f"Success Rate: {successful}/{len(history)} ({successful/len(history)*100:.1f}%)")
        print(f"\nAverage Metrics:")
        print(f"  CPU Usage: {avg_cpu:.1f}%")
        print(f"  Memory Usage: {avg_memory:.1f}%")
        print(f"  Response Time: {avg_response:.2f} ms")
        
        # التقييم
        print(f"\n{'='*70}")
        print(f"  Performance Rating")
        print(f"{'='*70}")
        
        if avg_response < 200 and avg_cpu < 50 and successful/len(history) > 0.95:
            print("⭐⭐⭐⭐⭐ Excellent - النظام يتحمل الضغط بشكل ممتاز")
        elif avg_response < 500 and avg_cpu < 70 and successful/len(history) > 0.90:
            print("⭐⭐⭐⭐ Good - النظام يتحمل الضغط بشكل جيد")
        elif avg_response < 1000 and avg_cpu < 85:
            print("⭐⭐⭐ Average - الأداء متوسط تحت الضغط")
        else:
            print("⭐⭐ Needs Optimization - يحتاج تحسينات")
        
        print(f"{'='*70}\n")


if __name__ == "__main__":
    print("\n📊 UAE-Sale Performance Monitor")
    print("تأكد من تشغيل السيرفر أولاً!\n")
    
    monitor = PerformanceMonitor()
    
    print("1. Quick Test (30 seconds)")
    print("2. Standard Test (60 seconds)")
    print("3. Extended Test (120 seconds)")
    
    choice = input("\nاختر (1-3): ").strip() or "1"
    
    durations = {'1': 30, '2': 60, '3': 120}
    duration = durations.get(choice, 30)
    
    monitor.monitor(duration)
    
    print("\n✅ Monitoring complete!")
    print("© 2025 Azad Smart Systems\n")

