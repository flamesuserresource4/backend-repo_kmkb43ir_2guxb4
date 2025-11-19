import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator
from typing import Literal, Optional, List, Tuple

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ProteinRequest(BaseModel):
    weight: float = Field(..., gt=0, description="Body weight value")
    unit: Literal["kg", "lb"] = Field("kg", description="Unit of weight")
    activity: Literal["low", "moderate", "high"] = Field(
        "moderate", description="Typical training volume/intensity"
    )
    goal: Literal["fat_loss", "maintenance", "muscle_gain"] = Field(
        "maintenance", description="Primary goal"
    )
    age: Optional[int] = Field(None, ge=10, le=100)
    sex: Optional[Literal["male", "female", "other"]] = None

    @validator("weight")
    def validate_weight(cls, v):
        if v > 1000:
            raise ValueError("Weight value seems unrealistic")
        return v


class MacroSplit(BaseModel):
    protein_g: int
    carbs_g: int
    fats_g: int
    split_percent: dict
    calories: int


class MealSuggestion(BaseModel):
    name: str
    tagline: str
    macros: MacroSplit
    sample_meals: List[str]


class ProteinResponse(BaseModel):
    weight_kg: float
    grams_per_kg_range: Tuple[float, float]
    daily_grams_min: int
    daily_grams_max: int
    daily_grams_target: int
    rationale: str
    suggestions: List[MealSuggestion]


@app.get("/")
def read_root():
    return {"message": "Hello from FastAPI Backend!"}


@app.get("/api/hello")
def hello():
    return {"message": "Hello from the backend API!"}


def _round5(x: float) -> int:
    return int(round(x / 5.0) * 5)


def _make_plan(name: str, tagline: str, pct: tuple[int, int, int], protein_g: int) -> MealSuggestion:
    p_pct, c_pct, f_pct = pct
    # Total calories derived from protein and split
    # protein kcal = protein_g*4 = p_pct% of total
    total_kcal = (protein_g * 4.0) / (p_pct / 100.0)
    carbs_g = total_kcal * (c_pct / 100.0) / 4.0
    fats_g = total_kcal * (f_pct / 100.0) / 9.0

    macros = MacroSplit(
        protein_g=_round5(protein_g),
        carbs_g=_round5(carbs_g),
        fats_g=_round5(fats_g),
        split_percent={"protein": p_pct, "carbs": c_pct, "fats": f_pct},
        calories=int(round(total_kcal)),
    )

    # Simple sample meals crafted to fit archetype theme
    base_meals = {
        "Lifting Beast": [
            "Breakfast: Greek yogurt parfait + oats + whey",
            "Lunch: Steak bowl with rice, beans, salsa",
            "Snack: Cottage cheese + fruit + almonds",
            "Dinner: Chicken thighs, potatoes, roasted veg",
        ],
        "Mat Dominator": [
            "Breakfast: Egg white omelet + spinach + toast",
            "Lunch: Turkey rice bowl + kimchi",
            "Snack: Beef jerky + banana",
            "Dinner: Salmon, quinoa, mixed greens",
        ],
        "Track Rocket": [
            "Breakfast: Protein pancakes + berries",
            "Lunch: Teriyaki chicken + jasmine rice",
            "Snack: Low-fat chocolate milk + pretzels",
            "Dinner: Lean beef pasta + tomato sauce",
        ],
        "Grand Tour Engine": [
            "Breakfast: Oats + honey + whey + banana",
            "Ride Fuel: Rice cakes + isotonic drink",
            "Lunch: Tuna baguette + fruit",
            "Dinner: Chicken risotto + olive oil drizzle",
        ],
    }

    meals = base_meals.get(name, [
        "Breakfast: Eggs + oats + fruit",
        "Lunch: Chicken rice bowl",
        "Snack: Yogurt + nuts",
        "Dinner: Fish, potatoes, vegetables",
    ])

    return MealSuggestion(name=name, tagline=tagline, macros=macros, sample_meals=meals)


@app.post("/api/protein", response_model=ProteinResponse)
def calculate_protein(req: ProteinRequest):
    # Convert to kg
    weight_kg = req.weight if req.unit == "kg" else req.weight * 0.45359237

    # Base range by activity
    if req.activity == "low":
        base_min, base_max = 1.2, 1.6
    elif req.activity == "moderate":
        base_min, base_max = 1.6, 2.0
    else:  # high
        base_min, base_max = 1.8, 2.2

    # Goal adjustments
    if req.goal == "fat_loss":
        base_min += 0.2
        base_max += 0.2
    elif req.goal == "muscle_gain":
        base_min += 0.1
        base_max += 0.1

    # Clamp to sensible range
    min_gkg = max(1.2, round(base_min, 2))
    max_gkg = min(2.7, round(base_max, 2))

    daily_min = int(round(min_gkg * weight_kg))
    daily_max = int(round(max_gkg * weight_kg))
    target = int(round(((min_gkg + max_gkg) / 2.0) * weight_kg))

    rationale = (
        "Based on your activity and goal, a range of "
        f"{min_gkg}-{max_gkg} g/kg is appropriate. "
        "Using your body weight, that translates to the amounts shown. "
        "Hitting the middle of the range is a practical daily target."
    )

    # Build themed meal suggestions with macro splits
    # Base splits per archetype
    archetypes = [
        ("Lifting Beast", "Build thick strength with steady carbs.", (30, 45, 25)),
        ("Mat Dominator", "Mat-ready power with cutting-edge leanness.", (35, 35, 30)),
        ("Track Rocket", "Explosive speed fueled by fast carbs.", (25, 50, 25)),
        ("Grand Tour Engine", "Endurance-first fuel for long days in the saddle.", (20, 60, 20)),
    ]

    # Adjust split subtly by user goal
    goal_adj = {"fat_loss": 5, "maintenance": 0, "muscle_gain": 0}
    p_bump = goal_adj.get(req.goal, 0)

    suggestions: List[MealSuggestion] = []
    for name, tag, (p, c, f) in archetypes:
        adj_p = min(45, p + p_bump)
        # reduce carbs primarily, keep fats steady unless carbs would go <35 then borrow from fats
        reduce_from_carbs = p_bump
        adj_c = max(30, c - reduce_from_carbs)
        total = adj_p + adj_c + f
        if total != 100:
            # Normalize by trimming fats if needed or adding to carbs
            diff = 100 - total
            f = max(20, f + diff)
        suggestions.append(_make_plan(name, tag, (adj_p, adj_c, f), target))

    return ProteinResponse(
        weight_kg=round(weight_kg, 2),
        grams_per_kg_range=(min_gkg, max_gkg),
        daily_grams_min=daily_min,
        daily_grams_max=daily_max,
        daily_grams_target=target,
        rationale=rationale,
        suggestions=suggestions,
    )


@app.get("/test")
def test_database():
    """Test endpoint to check if database is available and accessible"""
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }
    
    try:
        # Try to import database module
        from database import db
        
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Configured"
            response["database_name"] = db.name if hasattr(db, 'name') else "✅ Connected"
            response["connection_status"] = "Connected"
            
            # Try to list collections to verify connectivity
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]  # Show first 10 collections
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️  Available but not initialized"
            
    except ImportError:
        response["database"] = "❌ Database module not found (run enable-database first)"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"
    
    # Check environment variables
    import os
    response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
    response["database_name"] = "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set"
    
    return response


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
