"""Unit tests for NotificationService/SecurityService and SentimentAnalyzer."""
from datetime import datetime
from decimal import Decimal

import pytest

from models import Sale
from services.notification_service import NotificationService, SecurityService
from services.sentiment_service import SentimentAnalyzer


@pytest.fixture(autouse=True)
def _reset_service_state():
    NotificationService._notifications.clear()
    SecurityService._blacklist.clear()
    SecurityService._failed_attempts.clear()
    yield
    NotificationService._notifications.clear()
    SecurityService._blacklist.clear()
    SecurityService._failed_attempts.clear()


def _sale(db, customer_id, number, notes):
    sale = Sale(
        sale_number=number, customer_id=customer_id,
        total_amount=Decimal('100.000'), amount_base=Decimal('100.000'),
        notes=notes,
    )
    db.session.add(sale)
    return sale


class TestSendNotification:
    def test_creates_row_with_defaults(self):
        notif = NotificationService.send_notification('عنوان', 'رسالة')

        assert notif['id'] == 1
        assert notif['title'] == 'عنوان'
        assert notif['message'] == 'رسالة'
        assert notif['type'] == 'info'
        assert notif['data'] == {}
        assert notif['read'] is False
        parsed = datetime.fromisoformat(notif['timestamp'])
        assert parsed.year >= 2026

    def test_data_dict_and_type_preserved(self):
        notif = NotificationService.send_notification(
            't', 'm', notification_type='warning', data={'order': 42}
        )
        assert notif['type'] == 'warning'
        assert notif['data'] == {'order': 42}

    def test_ids_increment_per_send(self):
        first = NotificationService.send_notification('a', 'b')
        second = NotificationService.send_notification('c', 'd')
        assert second['id'] == first['id'] + 1
        assert len(NotificationService._notifications) == 2


class TestGetRecentNotifications:
    def test_returns_last_n_in_order(self):
        for i in range(12):
            NotificationService.send_notification(f't{i}', f'm{i}')

        recent = NotificationService.get_recent_notifications(limit=3)

        assert len(recent) == 3
        assert [n['title'] for n in recent] == ['t9', 't10', 't11']

    def test_default_limit_is_ten(self):
        for i in range(15):
            NotificationService.send_notification(f't{i}', f'm{i}')

        recent = NotificationService.get_recent_notifications()

        assert len(recent) == 10
        assert recent[0]['title'] == 't5'
        assert recent[-1]['title'] == 't14'

    def test_limit_larger_than_store_returns_all(self):
        NotificationService.send_notification('only', 'one')
        assert len(NotificationService.get_recent_notifications(limit=50)) == 1


class TestMarkAsRead:
    def test_marks_target_read_only(self):
        n1 = NotificationService.send_notification('a', 'b')
        n2 = NotificationService.send_notification('c', 'd')

        NotificationService.mark_as_read(n1['id'])

        store = NotificationService._notifications
        assert store[0]['read'] is True
        assert store[1]['read'] is False
        assert n2['read'] is False

    def test_unknown_id_is_noop(self):
        NotificationService.send_notification('a', 'b')
        NotificationService.mark_as_read(999)
        assert NotificationService._notifications[0]['read'] is False


class TestNotificationTemplates:
    def test_payment_received_template(self):
        notif = NotificationService.notify_payment_received(
            250.0, 'شركة النور', 'تحويل بنكي'
        )

        assert notif['type'] == 'success'
        assert '250.0' in notif['message']
        assert 'شركة النور' in notif['message']
        assert 'تحويل بنكي' in notif['message']
        assert notif['data'] == {'amount': 250.0, 'customer': 'شركة النور'}

    def test_security_alert_template(self):
        notif = NotificationService.notify_security_alert('محاولة اختراق', 'IP 1.2.3.4')

        assert notif['type'] == 'danger'
        assert notif['title'] == '🚨 تنبيه أمني'
        assert notif['message'] == 'محاولة اختراق: IP 1.2.3.4'
        assert notif['data']['alert_type'] == 'محاولة اختراق'

    def test_purchase_activated_template(self):
        notif = NotificationService.notify_purchase_activated('باقة ذهبية', 'أحمد')

        assert notif['type'] == 'info'
        assert 'باقة ذهبية' in notif['message']
        assert 'أحمد' in notif['message']
        assert notif['data'] == {'package': 'باقة ذهبية', 'customer': 'أحمد'}

    def test_auto_approval_template(self):
        notif = NotificationService.notify_auto_approval(7, 1750.5)

        assert notif['type'] == 'success'
        assert '7' in notif['message']
        assert '1750.5' in notif['message']
        assert notif['data'] == {'count': 7, 'amount': 1750.5}


class TestDetectSuspiciousActivity:
    def test_clean_activity_not_suspicious(self):
        result = SecurityService.detect_suspicious_activity(
            '10.0.0.8', 'Mozilla/5.0 Chrome', 'login'
        )

        assert result == {'suspicious': False}
        assert NotificationService._notifications == []

    @pytest.mark.parametrize('agent', [
        'Mozilla/5.0 (compatible; GoogleBot/2.1)',
        'python-crawler/1.0',
        'data-scraper service',
        'Acunetix-scanner',
    ])
    def test_suspicious_user_agents_flagged(self, agent):
        result = SecurityService.detect_suspicious_activity('10.0.0.9', agent, 'login')

        assert result == {'suspicious': True, 'reason': 'suspicious_user_agent'}
        assert len(NotificationService._notifications) == 1
        alert = NotificationService._notifications[0]
        assert alert['type'] == 'danger'
        assert agent[:100] in alert['message']

    def test_blacklisted_ip_flagged_and_notifies(self):
        SecurityService._blacklist.add('203.0.113.7')

        result = SecurityService.detect_suspicious_activity(
            '203.0.113.7', 'Mozilla/5.0', 'login'
        )

        assert result == {'suspicious': True, 'reason': 'blacklisted_ip'}
        assert len(NotificationService._notifications) == 1
        alert = NotificationService._notifications[0]
        assert alert['data']['alert_type'] == 'IP محظور'
        assert '203.0.113.7' in alert['data']['details']

    def test_five_failed_attempts_trigger_auto_blacklist(self):
        ip = '198.51.100.23'
        for _ in range(5):
            SecurityService.log_failed_attempt(ip)

        result = SecurityService.detect_suspicious_activity(ip, 'Mozilla/5.0', 'login')

        assert result == {'suspicious': True, 'reason': 'too_many_failed_attempts'}
        assert ip in SecurityService._blacklist
        assert NotificationService._notifications[-1]['data']['alert_type'] == 'IP محظور تلقائياً'

    def test_blacklist_check_wins_after_auto_ban(self):
        ip = '198.51.100.99'
        for _ in range(5):
            SecurityService.log_failed_attempt(ip)
        SecurityService.detect_suspicious_activity(ip, 'Mozilla/5.0', 'login')

        second = SecurityService.detect_suspicious_activity(ip, 'Mozilla/5.0', 'login')

        assert second == {'suspicious': True, 'reason': 'blacklisted_ip'}

    def test_below_threshold_not_blocked(self):
        ip = '192.0.2.55'
        for _ in range(4):
            SecurityService.log_failed_attempt(ip)

        result = SecurityService.detect_suspicious_activity(ip, 'Mozilla/5.0', 'login')

        assert result == {'suspicious': False}
        assert ip not in SecurityService._blacklist


class TestFailedAttemptTracking:
    def test_first_attempt_initializes_entry(self):
        SecurityService.log_failed_attempt('192.0.2.1')

        entry = SecurityService._failed_attempts['192.0.2.1']
        assert entry['count'] == 1
        assert entry['first_attempt'] is not None
        assert entry['last_attempt'] is not None

    def test_repeated_attempts_increment_count(self):
        SecurityService.log_failed_attempt('192.0.2.2')
        SecurityService.log_failed_attempt('192.0.2.2')
        SecurityService.log_failed_attempt('192.0.2.2')

        assert SecurityService._failed_attempts['192.0.2.2']['count'] == 3

    def test_reset_removes_entry(self):
        SecurityService.log_failed_attempt('192.0.2.3')
        SecurityService.reset_failed_attempts('192.0.2.3')

        assert '192.0.2.3' not in SecurityService._failed_attempts

    def test_reset_unknown_ip_is_safe(self):
        SecurityService.reset_failed_attempts('203.0.113.1')
        assert SecurityService._failed_attempts == {}


class TestSecurityStatus:
    def test_empty_state_reports_high(self):
        status = SecurityService.get_security_status()

        assert status == {
            'blacklisted_ips': 0,
            'failed_attempts': 0,
            'total_failed_count': 0,
            'security_level': 'high',
        }

    def test_counts_ips_and_totals(self):
        for ip in ['1.1.1.1', '2.2.2.2']:
            for _ in range(3):
                SecurityService.log_failed_attempt(ip)
        SecurityService._blacklist.update(['9.9.9.9'])

        status = SecurityService.get_security_status()

        assert status['failed_attempts'] == 2
        assert status['total_failed_count'] == 6
        assert status['blacklisted_ips'] == 1
        assert status['security_level'] == 'high'

    def test_level_medium_then_low_by_failed_attempts(self):
        for i in range(11):
            SecurityService._failed_attempts[f'10.0.0.{i}'] = {
                'count': 1, 'first_attempt': None, 'last_attempt': None,
            }
        assert SecurityService._calculate_security_level() == 'medium'

        for i in range(11, 21):
            SecurityService._failed_attempts[f'10.0.0.{i}'] = {
                'count': 1, 'first_attempt': None, 'last_attempt': None,
            }
        assert SecurityService._calculate_security_level() == 'low'

    def test_level_by_blacklist_size(self):
        SecurityService._blacklist.update([f'10.1.0.{i}' for i in range(6)])
        assert SecurityService._calculate_security_level() == 'medium'

        SecurityService._blacklist.update([f'10.2.0.{i}' for i in range(5)])
        assert SecurityService._calculate_security_level() == 'low'


class TestSentimentAnalysisBasics:
    def test_none_input_is_neutral(self):
        result = SentimentAnalyzer.analyze(None)

        assert result['sentiment'] == 'neutral'
        assert result['polarity'] == 0.0
        assert result['subjectivity'] == 0.0
        assert result['confidence'] == 0.0

    def test_empty_string_is_neutral(self):
        result = SentimentAnalyzer.analyze('   ')

        assert result['sentiment'] == 'neutral'
        assert result['polarity'] == 0.0

    def test_positive_english_text(self):
        result = SentimentAnalyzer.analyze('Excellent service and very fast delivery')

        assert result['sentiment'] == 'positive'
        assert result['polarity'] > 0.2
        assert result['positive_words'] >= 2
        assert result['negative_words'] == 0

    def test_negative_english_text(self):
        result = SentimentAnalyzer.analyze(
            'Terrible support, the shipment was late and the app has an error'
        )

        assert result['sentiment'] == 'negative'
        assert result['polarity'] < -0.2
        assert result['negative_words'] >= 2

    def test_positive_arabic_text(self):
        result = SentimentAnalyzer.analyze('الخدمة ممتازة والتوصيل سريع، شكرا لكم')

        assert result['sentiment'] == 'positive'
        assert result['polarity'] > 0.2
        assert result['positive_words'] >= 2

    def test_negative_arabic_text(self):
        result = SentimentAnalyzer.analyze('التوصيل متأخر والخدمة كانت فظيعه ومزعجة')

        assert result['sentiment'] == 'negative'
        assert result['polarity'] < -0.2

    def test_mixed_balanced_text_is_neutral(self):
        result = SentimentAnalyzer.analyze('excellent price but late delivery')

        assert result['positive_words'] == 1
        assert result['negative_words'] == 1
        assert result['sentiment'] == 'neutral'
        assert result['polarity'] == 0.0

    def test_no_sentiment_words_is_neutral(self):
        result = SentimentAnalyzer.analyze('the invoice number is four five six')

        assert result['sentiment'] == 'neutral'
        assert result['polarity'] == 0.0
        assert result['subjectivity'] == 0.0
        assert result['positive_words'] == 0
        assert result['negative_words'] == 0


class TestSentimentBoundsAndMetrics:
    def test_polarity_within_bounds_for_extremes(self):
        all_pos = SentimentAnalyzer.analyze(
            'excellent amazing wonderful perfect outstanding reliable honest accurate'
        )
        all_neg = SentimentAnalyzer.analyze(
            'bad terrible awful poor weak problem error issue delay fraud scam worst'
        )

        assert all_pos['polarity'] == 1.0
        assert all_neg['polarity'] == -1.0
        assert -1.0 <= all_neg['polarity'] <= 1.0
        assert -1.0 <= all_pos['polarity'] <= 1.0

    def test_subjectivity_and_confidence_ratios(self):
        result = SentimentAnalyzer.analyze('great product with fast shipping and clean design')

        expected_ratio = round(3 / 8, 2)
        assert result['subjectivity'] == expected_ratio
        assert result['confidence'] == expected_ratio
        assert 0.0 <= result['confidence'] <= 1.0

    def test_confidence_capped_at_one(self):
        result = SentimentAnalyzer.analyze('excellentgoodamazingwonderful')

        assert result['positive_words'] == 4
        assert result['confidence'] == 1.0

    def test_case_insensitive_matching(self):
        lower = SentimentAnalyzer.analyze('excellent service')
        upper = SentimentAnalyzer.analyze('EXCELLENT SERVICE')

        assert upper['sentiment'] == lower['sentiment'] == 'positive'
        assert upper['polarity'] == lower['polarity']


class TestAnalyzeCustomerFeedback:
    def test_combines_sale_notes_into_overall_sentiment(self, db, test_customer):
        db.session.add(_sale(db, test_customer.id, 'S-NS-0001', 'excellent and fast service'))
        db.session.add(_sale(db, test_customer.id, 'S-NS-0002', 'amazing support, thank you'))
        db.session.add(_sale(db, test_customer.id, 'S-NS-0003', None))
        db.session.commit()

        result = SentimentAnalyzer.analyze_customer_feedback(test_customer.id)

        assert result['overall_sentiment'] == 'positive'
        assert result['polarity'] == 1.0
        assert result['feedback_count'] == 2

    def test_negative_notes_detected(self, db, test_customer):
        db.session.add(_sale(db, test_customer.id, 'S-NS-0011', 'terrible late service'))
        db.session.add(_sale(db, test_customer.id, 'S-NS-0012', 'awful support and a big problem'))
        db.session.commit()

        result = SentimentAnalyzer.analyze_customer_feedback(test_customer.id)

        assert result['overall_sentiment'] == 'negative'
        assert result['polarity'] < 0
        assert result['feedback_count'] == 2

    def test_customer_without_notes_is_neutral(self, db, test_customer):
        db.session.add(_sale(db, test_customer.id, 'S-NS-0021', None))
        db.session.commit()

        result = SentimentAnalyzer.analyze_customer_feedback(test_customer.id)

        assert result == {'overall_sentiment': 'neutral', 'feedback_count': 0}

    def test_customer_without_sales_is_neutral(self, db, test_customer):
        result = SentimentAnalyzer.analyze_customer_feedback(test_customer.id)

        assert result['overall_sentiment'] == 'neutral'
        assert result['feedback_count'] == 0
