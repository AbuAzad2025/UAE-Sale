"""Train and calibrate a versioned local ERP model from bilingual synthetic commands."""

import argparse
import json
import random
from pathlib import Path

import torch
from torch.nn.functional import cross_entropy
from torch.nn.utils.rnn import pad_sequence

from bot_core.neural_nlu import feature, tokenize
from bot_core.neural_nlu.model import IntentNet

# Each set reserves two bilingual phrasings for calibration and two for evaluation.
_EXAMPLES = {
    "get_customer_balance": ("customer", (
        "كم رصيد {value}", "أريد معرفة رصيد {value}", "كم على {value} من ذمم",
        "balance of customer {value}", "show outstanding balance for {value}",
        "هل يوجد رصيد مستحق للعميل {value}", "how much does {value} still owe",
        "تحقق من الذمة المالية للزبون {value}", "display the customer balance for {value}",
        "اعرض الذمة المالية للعميل {value}", "what does {value} owe",
    )),
    "check_stock": ("reference", (
        "كم باقي من الصنف {value}", "هل القطعة {value} متوفرة", "أريد كمية المخزون للصنف {value}",
        "how many units of {value} are in stock", "inventory for SKU {value}",
        "استفسار عن المتوفر من القطعة {value}", "check whether part {value} is available",
        "شيك على المخزون للقطعة {value}", "show the available quantity for part {value}",
        "أريد أعرف شو المتوفر من {value}", "do we have part {value}",
    )),
    "get_invoice_status": ("reference", (
        "هل الفاتورة {value} مدفوعة", "متابعة فاتورة رقم {value}", "هل سدد الزبون الفاتورة {value}",
        "is invoice {value} paid", "where is invoice {value} in processing",
        "تحقق من دفع فاتورة المبيعات {value}", "show the payment status on invoice {value}",
        "ما حالة الدفع للفاتورة {value}", "check if invoice {value} has a payment",
        "أريد التحقق من دفع الفاتورة {value}", "look up payment for invoice {value}",
    )),
    "draft_customer": ("customer", (
        "أرغب بإضافة الزبون {value}", "افتح ملف عميل باسم {value}", "سجل عميل جديد {value}",
        "register a new client named {value}", "prepare to add the customer {value}",
        "بدي أسجل العميل {value} في النظام", "set up a new record for customer {value}",
        "افتح ملف الزبون الجديد {value}", "create a customer record for {value}",
        "بدي أسجل زبون اسمه {value}", "set up a customer record for {value}",
    )),
    "purchase_order": (None, (
        "أريد إنشاء أمر شراء", "نحتاج شراء قطع غيار من المورد", "جهز مسودة أمر للمورد",
        "prepare a purchase order for a supplier", "start an order to buy from the vendor",
        "بدي أعمل طلب توريد", "create a procurement order",
        "أريد إكمال بيانات أمر الشراء", "new order for purchasing",
    )),
    "sales_report": (None, (
        "احسب مجموع المبيعات اليوم", "قارن حجم المبيعات خلال الشهرين", "كم عدد فواتير البيع هذا الأسبوع",
        "compare sales totals for last month", "show sales report by currency",
        "ملخص المبيعات المؤكدة", "give me the sales summary for the week",
        "أحتاج تقرير المبيعات هذا الشهر", "summarize monthly sales",
    )),
    "stock_transfer": ("reference", (
        "انقل الصنف {value} من مستودع إلى آخر", "جهز طلب نقل مخزون للصنف {value}",
        "نحتاج تحويل الكمية من الصنف {value} بين المستودعات",
        "move inventory of SKU {value} between warehouses", "prepare a stock transfer for {value}",
        "أريد ترحيل الصنف {value} لمستودع آخر", "transfer item {value} to another warehouse",
        "أنشئ تحويل مخزني للصنف {value}", "draft warehouse transfer for part {value}",
    )),
    "draft_quote": ("customer", (
        "اعمل عرض سعر للعميل {value}", "جهز تسعيرة مبيعات للعميل {value}", "مسودة عرض أسعار باسم {value}",
        "prepare a price quotation for {value}", "draft a sales quote for customer {value}",
        "أرسل لي معاينة عرض سعر للعميل {value}", "make a quotation for the customer {value}",
        "أريد تسعيرة عن طلب {value}", "create a price quote for {value}",
    )),
    "guide": (None, (
        "مرحبا كيف الحال", "كيف أستخدم الدليل", "أين أفتح الصفحة الرئيسية",
        "hello can you explain the menu", "show the ERP manual",
        "اشرح طريقة تسجيل الدخول", "help me navigate the dashboard screen",
        "أريد إرشادات حول الشاشة الرئيسية", "where can I find the home page",
        "ما طريقة تسجيل الدخول للنظام", "help navigating the home screen",
    )),
}
_NAMES = (
    "شركة النور", "سارة محمد", "مؤسسة الأمل", "أحمد رامي", "شركة النخبة",
    "Atlas Trading", "Maya Ahmed", "Delta Supply", "Sunrise Group", "Nile Partners",
)
_ADDITIONAL_TRAINING = {
    "get_customer_balance": (
        "قيمة الذمم المدينة باسم {value}", "المستحق على حساب العميل {value}",
        "الذمة المالية الحالية للزبون {value}", "شو عليه مبالغ الزبون {value}",
        "كم مديونية العميل {value}", "مديونية الزبون {value}", "show receivables due from {value}",
        "remaining balance for {value}", "شو بذمة {value}", "الرصيد المدين على {value}",
    ),
    "draft_quote": (
        "جهز تسعيرة على الطلب باسم {value}", "التسعيرة للزبون {value}",
        "أريد عرضًا للأسعار على طلبية {value}", "سعّر الطلب للعميل {value}",
        "اعمل تسعيرة للطلبية باسم {value}", "اعرض مسودة سعر للزبون {value}",
        "prepare a price estimate for {value}", "put together a quote addressed to {value}",
    ),
    "purchase_order": (
        "open a new purchasing order", "draft the purchase document", "جهز أمر للمشتريات",
        "ابدأ معاملة مشتريات جديدة", "وثيقة شراء جديدة للمورد", "open a draft for a supplier purchase",
    ),
    "stock_transfer": (
        "حول {value} إلى مستودع مختلف", "نقل بضائع {value} بين المخازن", "انقل {value} للفرع الثاني",
        "warehouse relocation of {value}", "relocate the stock code {value} to another depot",
        "move {value} from one store to the next", "تحويل داخلي للقطعة {value} بين الفروع",
    ),
    "check_stock": (
        "توفر الصنف {value}", "شو كمية {value} الباقية بالمخزن", "اعرض الكمية المتبقية من {value}",
        "show remaining stock for {value}", "do we currently have any {value}", "availability of {value}",
    ),
    "get_invoice_status": (
        "هل دفعوا الفاتورة {value}", "سداد الفاتورة {value}", "حتى الآن لم تسدد فاتورة {value}؟",
        "is {value} settled yet", "payment confirmation for {value}", "does {value} remain unpaid",
    ),
    "draft_customer": (
        "تسجيل زبون لأول مرة باسم {value}", "جهز بطاقة عميل جديد باسم {value}", "onboard client {value}",
        "open a profile for the new client {value}",
    ),
    "sales_report": (
        "إجمالي إيرادات البيع هذا الأسبوع", "احسب قيمة فواتير المبيعات خلال الشهر السابق",
        "aggregate confirmed sales this week", "weekly sales revenue summary",
    ),
    "guide": (
        "وين ألقى شاشة البرنامج", "كيف أوصل للقائمة", "وين موجودة الصفحة الرئيسية",
        "how do i open the help screen", "how can i access the navigation menu", "where is the erp start page",
    ),
}
_FEATURE_VERSION = 3


def _dataset(split: int, *, expanded: bool = False) -> list[tuple[list[str], str, list[str]]]:
    output = []
    for intent, (kind, phrases) in _EXAMPLES.items():
        selected = phrases[:-4] if split == 0 else phrases[-4:-2] if split == 1 else phrases[-2:]
        if expanded and split == 0:
            selected += _ADDITIONAL_TRAINING.get(intent, ())
        for template in selected:
            for number in range(14 if kind or split == 0 else 1):
                if kind == "customer":
                    value = _NAMES[(number + split) % len(_NAMES)]
                elif kind == "reference":
                    prefix = "INV" if intent == "get_invoice_status" else "SKU"
                    value = f"{prefix}-{split + 1}{number:03d}"
                else:
                    value = ""
                if "{value}" in template:
                    before, after = template.split("{value}")
                    leading, entity, trailing = tokenize(before), tokenize(value), tokenize(after)
                    tags = [f"B-{kind}"] + [f"I-{kind}"] * (len(entity) - 1)
                    output.append((
                        leading + entity + trailing, intent,
                        ["O"] * len(leading) + tags + ["O"] * len(trailing),
                    ))
                else:
                    tokens = tokenize(template)
                    output.append((tokens, intent, ["O"] * len(tokens)))
    return output


def _employee_rows(path: Path | None) -> tuple[list, list, list]:
    splits = {"train": [], "calibration": [], "evaluation": []}
    seen = set()
    if path is None:
        return tuple(splits.values())
    synthetic = {tuple(tokens) for split in range(3) for tokens, _, _ in _dataset(split, expanded=True)}
    for line_number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            split, intent = row["split"], row["intent"]
            words = tokenize(row["text"])
            entity = tokenize(row.get("entity", ""))
            kind = _EXAMPLES[intent][0]
            key = tuple(words)
            if split not in splits or not words or key in seen or key in synthetic:
                raise ValueError
            tags = ["O"] * len(words)
            if entity:
                matches = [index for index in range(len(words)) if words[index:index + len(entity)] == entity]
                if kind is None or len(matches) != 1:
                    raise ValueError
                start = matches[0]
                tags[start:start + len(entity)] = [f"B-{kind}"] + [f"I-{kind}"] * (len(entity) - 1)
            splits[split].append((words, intent, tags))
            seen.add(key)
        except (KeyError, IndexError, TypeError, AttributeError, ValueError) as error:
            raise ValueError(f"Invalid or duplicate labeled employee example on line {line_number}.") from error
    if not all(splits.values()):
        raise ValueError("Employee examples require train, calibration, and evaluation splits.")
    return tuple(splits.values())


def train(directory: Path, *, epochs: int = 25, employee_corpus: Path | None = None) -> dict:
    torch.set_num_threads(1)
    torch.manual_seed(17)
    training, calibration, evaluation = (_dataset(split, expanded=True) for split in range(3))
    employee_train, employee_calibration, employee_evaluation = _employee_rows(employee_corpus)
    training += employee_train
    calibration += employee_calibration
    intents = sorted(_EXAMPLES)
    tags = sorted({tag for _, _, sequence in training for tag in sequence})
    features = sorted({feature(token, _FEATURE_VERSION) for tokens, _, _ in training for token in tokens})
    vocab = {value: index for index, value in enumerate(["<pad>", "<unknown>", *features])}

    def batch(rows):
        inputs = [torch.tensor([vocab.get(feature(token, _FEATURE_VERSION), 1) for token in tokens]) for tokens, _, _ in rows]
        intent = torch.tensor([intents.index(label) for _, label, _ in rows])
        entities = [torch.tensor([tags.index(tag) for tag in sequence]) for _, _, sequence in rows]
        return pad_sequence(inputs, batch_first=True), intent, pad_sequence(entities, batch_first=True, padding_value=-100)

    model = IntentNet(len(vocab), len(intents), len(tags))
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.007)
    rng = random.Random(17)
    for _ in range(epochs):
        rng.shuffle(training)
        for start in range(0, len(training), 32):
            inputs, expected, expected_tags = batch(training[start:start + 32])
            intent, entities = model(inputs)
            loss = cross_entropy(intent, expected) + cross_entropy(
                entities.flatten(0, 1), expected_tags.flatten(),
            )
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

    model.eval()
    with torch.no_grad():
        inputs, labels, _ = batch(calibration)
        scores, _ = model(inputs)
        candidates = [index / 10 for index in range(5, 51)]
        temperature = min(candidates, key=lambda value: float(cross_entropy(scores / value, labels)))
        inputs, labels, expected_tags = batch(evaluation)
        scores, predicted_tags = model(inputs)
        mask = expected_tags != -100
        entity_mask = mask & (expected_tags != tags.index("O"))
        report = {
            "evaluation_examples": len(evaluation),
            "intent_accuracy": float((scores.argmax(1) == labels).float().mean()),
            "token_accuracy": float((predicted_tags.argmax(-1)[mask] == expected_tags[mask]).float().mean()),
            "entity_token_accuracy": float(
                (predicted_tags.argmax(-1)[entity_mask] == expected_tags[entity_mask]).float().mean()
            ),
            "calibrated_nll": float(cross_entropy(scores / temperature, labels)),
        }
        if employee_evaluation:
            inputs, labels, _ = batch(employee_evaluation)
            scores, _ = model(inputs)
            report["employee_evaluation_examples"] = len(employee_evaluation)
            report["employee_intent_accuracy"] = float((scores.argmax(1) == labels).float().mean())
    directory.mkdir(parents=True, exist_ok=False)
    torch.save(model.state_dict(), directory / "model.pt")
    metadata = {
        "version": directory.name, "vocab": vocab, "intents": intents,
        "tags": tags, "temperature": temperature, "evaluation": report, "feature_version": _FEATURE_VERSION,
    }
    (directory / "vocab.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=25)
    parser.add_argument("--employee-corpus", type=Path)
    args = parser.parse_args()
    if args.epochs < 1:
        parser.error("--epochs must be positive")
    print(json.dumps(train(args.output, epochs=args.epochs, employee_corpus=args.employee_corpus)))


if __name__ == "__main__":
    main()
