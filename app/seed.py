from app.database import SessionLocal, Base, engine
from app import models

Base.metadata.create_all(bind=engine)

db = SessionLocal()

merchant = models.Merchant(name="Demo Store")
db.add(merchant)
db.commit()
db.refresh(merchant)

products = [
    dict(name="Mechanical Keyboard - Red Switch", category="keyboards", price=179900, stock=42,
         agent_metadata={"best_for": ["programming", "office"], "not_ideal_for": ["quiet rooms"],
                          "compatible_with": ["Windows", "MacOS", "Linux"], "return_days": 7, "warranty_months": 12,
                          "frequently_bought_with": [3]}),
    dict(name="Wireless Compact Keyboard", category="keyboards", price=149900, stock=30,
         agent_metadata={"best_for": ["office", "travel"], "compatible_with": ["Windows", "MacOS"],
                          "return_days": 7, "warranty_months": 12,
                          "frequently_bought_with": [3]}),
    dict(name="Ergonomic Wrist Rest", category="accessories", price=29900, stock=100,
         agent_metadata={"best_for": ["long typing sessions"], "compatible_with": ["universal"],
                          "return_days": 7, "warranty_months": 0}),
    dict(name="Noise Cancelling Headphones", category="audio", price=349900, stock=25,
         agent_metadata={"best_for": ["focus work", "calls"], "compatible_with": ["Bluetooth"],
                          "return_days": 10, "warranty_months": 12}),
    dict(name="Budget Wired Headphones", category="audio", price=59900, stock=60,
         agent_metadata={"best_for": ["calls", "casual listening"], "compatible_with": ["3.5mm jack"],
                          "return_days": 7, "warranty_months": 6}),
    dict(name="Laptop Stand - Aluminium", category="accessories", price=139900, stock=40,
         agent_metadata={"best_for": ["ergonomics", "coding setup"], "compatible_with": ["13-17 inch laptops"],
                          "return_days": 7, "warranty_months": 12}),
    dict(name="14-inch Programming Laptop", category="laptops", price=5499900, stock=15,
         agent_metadata={"best_for": ["coding", "development"], "compatible_with": ["universal"],
                          "return_days": 7, "warranty_months": 12,
                          "frequently_bought_with": [6, 9, 10]}),
    dict(name="16-inch Pro Laptop", category="laptops", price=5899900, stock=10,
         agent_metadata={"best_for": ["coding", "heavy multitasking"], "compatible_with": ["universal"],
                          "return_days": 14, "warranty_months": 12,
                          "frequently_bought_with": [6, 9, 10]}),
    dict(name="Laptop Carrying Case", category="accessories", price=99900, stock=50,
         agent_metadata={"best_for": ["travel", "protection"], "compatible_with": ["13-16 inch laptops"],
                          "return_days": 7, "warranty_months": 0}),
    dict(name="USB-C Hub 7-in-1", category="accessories", price=189900, stock=35,
         agent_metadata={"best_for": ["connectivity"], "compatible_with": ["USB-C laptops"],
                          "return_days": 7, "warranty_months": 12}),
    dict(name="External SSD 1TB", category="storage", price=749900, stock=20,
         agent_metadata={"best_for": ["backups", "large projects"], "compatible_with": ["USB-C", "USB-A"],
                          "return_days": 7, "warranty_months": 36}),
    dict(name="27-inch Monitor", category="displays", price=1899900, stock=18,
         agent_metadata={"best_for": ["coding", "multitasking"], "compatible_with": ["HDMI", "DisplayPort"],
                          "return_days": 10, "warranty_months": 24,
                          "frequently_bought_with": [14, 10]}),
    dict(name="Desk Mat XL", category="accessories", price=79900, stock=45,
         agent_metadata={"best_for": ["desk setup"], "compatible_with": ["universal"],
                          "return_days": 7, "warranty_months": 0}),
    dict(name="Webcam 1080p", category="accessories", price=249900, stock=28,
         agent_metadata={"best_for": ["video calls", "streaming"], "compatible_with": ["USB"],
                          "return_days": 7, "warranty_months": 12}),
    dict(name="Office Chair - Mesh Back", category="furniture", price=849900, stock=12,
         agent_metadata={"best_for": ["long work hours", "ergonomics"], "compatible_with": ["universal"],
                          "return_days": 15, "warranty_months": 24,
                          "frequently_bought_with": [13]}),
]

for p in products:
    db.add(models.Product(merchant_id=merchant.id, **p))

db.commit()

print(f"Seeded merchant '{merchant.name}' (id={merchant.id}) with {len(products)} products")
policy = models.AgentPolicy(
    agent_id="buyer_agent_1",
    max_transaction=500000,          # ₹5,000 — absolute ceiling, never allowed above this
    daily_limit=1000000,             # ₹10,000
    allowed_categories=["keyboards", "accessories", "audio", "laptops", "storage", "displays", "furniture"],
    requires_approval_above=200000,  # ₹2,000 — auto-approve up to here; ₹2,000-₹5,000 needs human approval
)
db.add(policy)
db.commit()
print(f"Seeded agent policy for '{policy.agent_id}'")

db.close()