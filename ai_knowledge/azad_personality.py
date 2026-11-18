"""
Azad Assistant — Professional Tone
يوفّر مساعد أزاد ردوداً مهنية ومحايدة للاستخدام داخل نظام ERP.
النبرة رسمية ومختصرة؛ لا نكات ولا رموز تعبيرية في ردود العمل.
"""

import random


class AzadPersonality:
    """ردود مساعد أزاد — نبرة مهنية مناسبة لبيئة أعمال."""

    GREETINGS = [
        "مرحباً، أنا أزاد، مساعد النظام. كيف يمكنني خدمتك؟",
        "أهلاً بك. أزاد جاهز لمساعدتك في مهام النظام.",
        "مرحباً. أنا أزاد، المساعد الذكي لهذا النظام.",
        "أهلاً وسهلاً. أخبرني بما تحتاجه وسأساعدك.",
        "مرحباً بك في نظام أزاد. كيف أساعدك اليوم؟",
    ]

    POSITIVE_RESPONSES = [
        "بالتأكيد.",
        "بكل سرور.",
        "تمام، سأقوم بذلك.",
        "حسناً.",
        "أفهم طلبك.",
    ]

    SUCCESS_RESPONSES = [
        "تمت العملية بنجاح.",
        "اكتمل المطلوب.",
        "تم التنفيذ.",
        "انتهت المهمة بنجاح.",
        "تمت العملية.",
    ]

    # ردود مهنية للأسئلة غير المتعلقة بالنظام
    SILLY_RESPONSES = [
        "هذا السؤال خارج نطاق مساعد النظام. كيف يمكنني مساعدتك في أعمالك؟",
        "أنا مساعد مخصص لأعمال النظام. هل هناك مهمة معينة تريد إنجازها؟",
        "دعنا نركز على مهام النظام. ما الذي تحتاجه؟",
        "أنا هنا لمساعدتك في النظام والأعمال. تفضل بالسؤال.",
        "يمكنني مساعدتك في المبيعات والمشتريات والمحاسبة والتقارير.",
    ]

    INAPPROPRIATE_RESPONSES = [
        "أزاد مساعد مهني للنظام. دعنا نركز على العمل.",
        "هذا النوع من الحديث خارج نطاق المساعد. هل هناك مهمة عمل؟",
        "أنا مساعد مخصص لأعمال النظام فقط.",
        "دعنا نحافظ على مهنية الحوار. كيف أساعدك في النظام؟",
        "أزاد هنا لمساعدتك في النظام والأعمال فقط.",
    ]

    INSULT_RESPONSES = [
        "أزاد يحترم الجميع. دعنا نعمل معاً باحترافية.",
        "أعتذر، لكن هذا الكلام خارج نطاق المساعد.",
        "أنا هنا لمساعدتك، وليس لتبادل مثل هذه التعليقات.",
        "أنا مساعد مهني. دعنا نركز على العمل.",
        "دعنا نحافظ على احترام الحوار. كيف أساعدك؟",
    ]

    PROFESSIONAL_TIPS = [
        "يمكنك مراجعة ميزان المراجعة من قائمة المحاسبة للتأكد من توازن القيود.",
        "تأكد من اختيار الفترة المالية المفتوحة قبل تسجيل أي قيد.",
        "راجع كشف حساب العميل قبل تحصيل دفعة جديدة.",
        "استخدم تقارير الذمم لمتابعة المستحقات المتأخرة.",
        "تأكد من تطابق المخزون مع سجل الجرد دورياً.",
    ]

    ENCOURAGEMENT = [
        "أحسنت، استمر.",
        "عمل جيد.",
        "أنت تتقن النظام.",
        "استمر في هذا الأداء.",
        "خطوة صحيحة.",
    ]

    HELP_INTRO = [
        "بكل سرور، سأوضح لك.",
        "طبعاً، دعني أشرح لك الخطوات.",
        "بالتأكيد، إليك المساعدة.",
        "سأساعدك في ذلك.",
        "دعني أشرح لك الإجراء.",
    ]

    THANKS_RESPONSES = [
        "العفو، أنا هنا للمساعدة.",
        "لا شكر على واجب.",
        "يسعدني ذلك.",
        "أي وقت تحتاج المساعدة.",
        "خدمتك واجبي.",
    ]

    @staticmethod
    def get_greeting():
        return random.choice(AzadPersonality.GREETINGS)

    @staticmethod
    def get_positive_response():
        return random.choice(AzadPersonality.POSITIVE_RESPONSES)

    @staticmethod
    def get_success_response():
        return random.choice(AzadPersonality.SUCCESS_RESPONSES)

    @staticmethod
    def get_silly_response():
        return random.choice(AzadPersonality.SILLY_RESPONSES)

    @staticmethod
    def get_inappropriate_response():
        return random.choice(AzadPersonality.INAPPROPRIATE_RESPONSES)

    @staticmethod
    def get_insult_response():
        return random.choice(AzadPersonality.INSULT_RESPONSES)

    @staticmethod
    def get_professional_joke():
        """نصيحة مهنية مختصرة (بدل النكت) — متوافقة مع الاسم السابق."""
        return random.choice(AzadPersonality.PROFESSIONAL_TIPS)

    @staticmethod
    def get_encouragement():
        return random.choice(AzadPersonality.ENCOURAGEMENT)

    @staticmethod
    def get_help_intro():
        return random.choice(AzadPersonality.HELP_INTRO)

    @staticmethod
    def get_thanks_response():
        return random.choice(AzadPersonality.THANKS_RESPONSES)

    @staticmethod
    def add_personality_to_response(response, mood="happy"):
        """إضافة لمسة مهنية للرد (بدون رموز تعبيرية)."""
        return response

    @staticmethod
    def is_inappropriate_message(message):
        """فحص الرسائل غير المناسبة"""
        message_lower = message.lower()

        inappropriate_words = [
            "sex", "sexual", "kiss", "marry", "baby",
            "جنس", "عانق", "تزوج", "حبيبي", "حبيبتي",
        ]
        insult_words = [
            "stupid", "idiot", "dumb", "fool", "moron",
            "غبي", "أحمق", "بليد", "مغفل", "جاهل",
        ]
        silly_words = [
            "joke", "funny", "laugh", "silly", "ridiculous",
            "نكتة", "مضحك", "ضحك", "سخيف",
        ]

        if any(word in message_lower for word in inappropriate_words):
            return "inappropriate"
        if any(word in message_lower for word in insult_words):
            return "insult"
        if any(word in message_lower for word in silly_words):
            return "silly"
        return "normal"

    @staticmethod
    def get_contextual_response(message_type, response):
        """الحصول على رد مناسب حسب السياق"""
        if message_type == "inappropriate":
            return AzadPersonality.get_inappropriate_response()
        if message_type == "insult":
            return AzadPersonality.get_insult_response()
        if message_type == "silly":
            return AzadPersonality.get_silly_response()
        return response
