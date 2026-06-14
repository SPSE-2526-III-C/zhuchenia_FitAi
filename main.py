import os
import csv
import io
import uuid
from datetime import datetime, timedelta
from collections import defaultdict

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    jsonify,
    make_response,
    Response,
    session
)

from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt

from flask_login import (
    UserMixin,
    LoginManager,
    login_user,
    logout_user,
    login_required,
    current_user
)

from forms import RegistrationForm, LoginForm

import google.generativeai as genai
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


# =========================
# ENV
# =========================
load_dotenv()


# =========================
# APP
# =========================
app = Flask(__name__)

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///fitness.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'your_secret_key'
app.config['WTF_CSRF_ENABLED'] = False


# =========================
# EXTENSIONS
# =========================
db = SQLAlchemy()
bcrypt = Bcrypt()
login_manager = LoginManager()

db.init_app(app)
bcrypt.init_app(app)
login_manager.init_app(app)

login_manager.login_view = 'login'


# =========================
# MODELS
# =========================
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)
    goal = db.Column(db.String(80), default='Sila')
    level = db.Column(db.String(80), default='Začiatočník')


class Workout(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.DateTime, default=datetime.now)

    exercise = db.Column(db.String(100), nullable=False)
    weight = db.Column(db.String(20), nullable=False)
    reps = db.Column(db.String(20), nullable=False)
    workout_type = db.Column(db.String(50))
    sets = db.Column(db.String(20), default='3')
    session_id = db.Column(db.String(80))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    user = db.relationship('User', backref='workouts')


# =========================
# USER LOADER
# =========================
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# =========================
# DB INIT / LIGHT MIGRATION
# =========================
def add_column_if_missing(table_name, column_name, column_sql):
    columns = db.session.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
    existing_columns = [column[1] for column in columns]

    if column_name not in existing_columns:
        db.session.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_sql}"))
        db.session.commit()


with app.app_context():
    db.create_all()
    add_column_if_missing('user', 'goal', "goal VARCHAR(80) DEFAULT 'Sila'")
    add_column_if_missing('user', 'level', "level VARCHAR(80) DEFAULT 'Začiatočník'")
    add_column_if_missing('workout', 'user_id', 'user_id INTEGER')
    add_column_if_missing('workout', 'sets', "sets VARCHAR(20) DEFAULT '3'")
    add_column_if_missing('workout', 'session_id', 'session_id VARCHAR(80)')


# =========================
# AI
# =========================
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))


GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest")


def get_user_workouts():
    return Workout.query.filter_by(user_id=current_user.id)


def parse_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0


def parse_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def get_progress_status(workout_count):
    if workout_count < 5:
        return "Začiatočník"
    if workout_count < 15:
        return "Stredná úroveň"
    return "Pokročilý"


def build_workout_summary(workouts):
    if not workouts:
        return "Používateľ zatiaľ nemá uložené tréningy."

    lines = []
    for workout in workouts[:10]:
        lines.append(
            f"{workout.date.strftime('%d.%m.%Y')}: {workout.exercise}, "
            f"{workout.weight} kg, {workout.reps} opakovaní, typ {workout.workout_type or 'nezadaný'}"
        )

    return "\n".join(lines)


def get_exercise_visual(exercise_name):
    name = exercise_name.lower()

    if any(word in name for word in ["squat", "leg", "lunge", "calf"]):
        return {"label": "LEGS", "color": "#dc3545", "path": "M95 150 L130 95 L165 150 M130 95 L130 55 M110 70 L150 70 M110 190 L130 150 L150 190"}
    if any(word in name for word in ["pull", "row", "lat", "biceps"]):
        return {"label": "PULL", "color": "#198754", "path": "M80 62 H180 M105 62 L105 105 M155 62 L155 105 M130 105 L105 155 M130 105 L155 155 M105 155 L92 198 M155 155 L168 198"}
    if any(word in name for word in ["bench", "press", "dips", "triceps", "push"]):
        return {"label": "PUSH", "color": "#0d6efd", "path": "M80 145 H180 M95 128 H165 M105 128 L95 165 M155 128 L165 165 M130 92 L105 128 M130 92 L155 128 M105 82 H155"}
    if any(word in name for word in ["plank", "raises", "core"]):
        return {"label": "CORE", "color": "#ffc107", "path": "M70 150 H185 M92 150 L120 112 L155 112 L180 150 M85 178 H175 M115 112 L115 82 M145 112 L145 82"}

    return {"label": "FITAI", "color": "#0dcaf0", "path": "M95 165 L130 90 L165 165 M110 132 H150 M130 90 L130 55 M105 75 H155"}


def get_exercise_group(exercise_name):
    name = exercise_name.lower()

    if any(word in name for word in ["bench", "press", "dips", "triceps", "push"]):
        return "Push"
    if any(word in name for word in ["pull", "row", "lat", "biceps"]):
        return "Pull"
    if any(word in name for word in ["squat", "leg", "lunge", "calf"]):
        return "Legs"
    if any(word in name for word in ["plank", "raises", "core"]):
        return "Core"

    return "Full Body"


app.jinja_env.globals.update(get_exercise_group=get_exercise_group)


@app.route('/exercise_image/<path:exercise_name>')
def exercise_image(exercise_name):
    visual = get_exercise_visual(exercise_name)
    title = exercise_name.replace("&", "and")

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 260 220" role="img" aria-label="{title}">
<defs>
  <linearGradient id="bg" x1="0" x2="1" y1="0" y2="1">
    <stop offset="0" stop-color="#101010"/>
    <stop offset="1" stop-color="#1e1e1e"/>
  </linearGradient>
</defs>
<rect width="260" height="220" fill="url(#bg)"/>
<circle cx="205" cy="45" r="54" fill="{visual['color']}" opacity="0.16"/>
<circle cx="55" cy="182" r="46" fill="{visual['color']}" opacity="0.12"/>
<path d="{visual['path']}" fill="none" stroke="{visual['color']}" stroke-width="12" stroke-linecap="round" stroke-linejoin="round"/>
<circle cx="130" cy="42" r="18" fill="{visual['color']}" opacity="0.95"/>
<text x="18" y="32" fill="#f8f9fa" font-family="Arial, sans-serif" font-size="15" font-weight="700">{visual['label']}</text>
<text x="18" y="202" fill="#f8f9fa" font-family="Arial, sans-serif" font-size="18" font-weight="700">{title}</text>
</svg>"""

    return Response(svg, mimetype='image/svg+xml')


def get_plan_data():
    return [
        {
            "slug": "push",
            "name": "Push",
            "goal": "Sila a vrch tela",
            "description": "Silový plán pre používateľa, ktorý chce výraznejší hrudník, pevnejšie ramená a silnejší triceps. Hodí sa, keď chceš zlepšiť tlakové cviky a budovať vrch tela kontrolovane, bez zbytočného preplnenia tréningu.",
            "color": "primary",
            "image": "https://images.unsplash.com/photo-1534367610401-9f5ed68180aa?auto=format&fit=crop&w=900&q=80",
            "schedule": "Pondelok alebo štvrtok",
            "exercises": [
                {"name": "Bench press", "sets": "4", "reps": "8", "weight": "60", "image": "https://images.unsplash.com/photo-1581009146145-b5ef050c2e1e?auto=format&fit=crop&w=700&q=80"},
                {"name": "Overhead press", "sets": "3", "reps": "10", "weight": "30", "image": "https://images.unsplash.com/photo-1599058917212-d750089bc07e?auto=format&fit=crop&w=700&q=80"},
                {"name": "Dips", "sets": "3", "reps": "10", "weight": "0", "image": "https://images.unsplash.com/photo-1598971639058-fab3c3109a00?auto=format&fit=crop&w=700&q=80"},
                {"name": "Triceps pushdown", "sets": "3", "reps": "12", "weight": "25", "image": "https://images.unsplash.com/photo-1583454110551-21f2fa2afe61?auto=format&fit=crop&w=700&q=80"}
            ]
        },
        {
            "slug": "pull",
            "name": "Pull",
            "goal": "Chrbát a ťahová sila",
            "description": "Plán zameraný na silný chrbát, lepšie držanie tela a biceps. Je vhodný, keď chceš vyvážiť tlakové tréningy, zlepšiť ťahovú silu a postupne budovať širší, stabilnejší vrch tela.",
            "color": "success",
            "image": "https://images.unsplash.com/photo-1598971639058-fab3c3109a00?auto=format&fit=crop&w=900&q=80",
            "schedule": "Utorok alebo piatok",
            "exercises": [
                {"name": "Pull-ups", "sets": "4", "reps": "6", "weight": "0", "image": "https://images.unsplash.com/photo-1598971639058-fab3c3109a00?auto=format&fit=crop&w=700&q=80"},
                {"name": "Barbell row", "sets": "4", "reps": "8", "weight": "50", "image": "https://images.unsplash.com/photo-1583454110551-21f2fa2afe61?auto=format&fit=crop&w=700&q=80"},
                {"name": "Lat pulldown", "sets": "3", "reps": "10", "weight": "45", "image": "https://images.unsplash.com/photo-1574680096145-d05b474e2155?auto=format&fit=crop&w=700&q=80"},
                {"name": "Biceps curl", "sets": "3", "reps": "12", "weight": "12", "image": "https://images.unsplash.com/photo-1581009137042-c552e485697a?auto=format&fit=crop&w=700&q=80"}
            ]
        },
        {
            "slug": "legs",
            "name": "Legs",
            "goal": "Nohy a core",
            "description": "Ťažší základový plán pre stehná, zadok, lýtka a stabilitu. Najviac sa hodí vtedy, keď chceš silnejší spodok tela, lepší výkon v základných cvikoch a pevnejší core pri každom tréningu.",
            "color": "danger",
            "image": "https://images.unsplash.com/photo-1434682881908-b43d0467b798?auto=format&fit=crop&w=900&q=80",
            "schedule": "Streda alebo sobota",
            "exercises": [
                {"name": "Squat", "sets": "4", "reps": "8", "weight": "70", "image": "https://images.unsplash.com/photo-1434682881908-b43d0467b798?auto=format&fit=crop&w=700&q=80"},
                {"name": "Leg press", "sets": "4", "reps": "10", "weight": "120", "image": "https://images.unsplash.com/photo-1574680178050-55c6a6a96e0a?auto=format&fit=crop&w=700&q=80"},
                {"name": "Lunges", "sets": "3", "reps": "12", "weight": "20", "image": "https://images.unsplash.com/photo-1605296867304-46d5465a13f1?auto=format&fit=crop&w=700&q=80"},
                {"name": "Calf raises", "sets": "3", "reps": "15", "weight": "40", "image": "https://images.unsplash.com/photo-1599058917212-d750089bc07e?auto=format&fit=crop&w=700&q=80"}
            ]
        },
        {
            "slug": "full-body",
            "name": "Full Body",
            "goal": "Celková kondícia",
            "description": "Praktický tréning celého tela pre dni, keď chceš spraviť veľa práce naraz. Spája tlak, ťah, nohy aj core, takže je dobrý na pravidelnosť, kondíciu a celkový progres bez komplikovaného plánovania.",
            "color": "warning",
            "image": "https://images.unsplash.com/photo-1517836357463-d25dfeac3438?auto=format&fit=crop&w=900&q=80",
            "schedule": "3x týždenne",
            "exercises": [
                {"name": "Squat", "sets": "3", "reps": "10", "weight": "50", "image": "https://images.unsplash.com/photo-1434682881908-b43d0467b798?auto=format&fit=crop&w=700&q=80"},
                {"name": "Bench press", "sets": "3", "reps": "10", "weight": "45", "image": "https://images.unsplash.com/photo-1581009146145-b5ef050c2e1e?auto=format&fit=crop&w=700&q=80"},
                {"name": "Row", "sets": "3", "reps": "10", "weight": "40", "image": "https://images.unsplash.com/photo-1583454110551-21f2fa2afe61?auto=format&fit=crop&w=700&q=80"},
                {"name": "Plank", "sets": "3", "reps": "45s", "weight": "0", "image": "https://images.unsplash.com/photo-1571019613914-85f342c1d3e8?auto=format&fit=crop&w=700&q=80"}
            ]
        },
        {
            "slug": "calisthenics",
            "name": "Calisthenics",
            "goal": "Vlastná váha",
            "description": "Plán pre vlastnú váhu, kontrolu tela a silu bez strojov. Hodí sa, keď chceš trénovať flexibilne, zlepšiť zhyby, kľuky, dipsy a cítiť väčšiu kontrolu nad vlastným pohybom.",
            "color": "info",
            "image": "https://images.unsplash.com/photo-1598971639058-fab3c3109a00?auto=format&fit=crop&w=900&q=80",
            "schedule": "2-4x týždenne",
            "exercises": [
                {"name": "Push-ups", "sets": "4", "reps": "12", "weight": "0", "image": "https://images.unsplash.com/photo-1598971639058-fab3c3109a00?auto=format&fit=crop&w=700&q=80"},
                {"name": "Pull-ups", "sets": "4", "reps": "6", "weight": "0", "image": "https://images.unsplash.com/photo-1598971639058-fab3c3109a00?auto=format&fit=crop&w=700&q=80"},
                {"name": "Dips", "sets": "3", "reps": "10", "weight": "0", "image": "https://images.unsplash.com/photo-1574680096145-d05b474e2155?auto=format&fit=crop&w=700&q=80"},
                {"name": "Hanging leg raises", "sets": "3", "reps": "10", "weight": "0", "image": "https://images.unsplash.com/photo-1571019613454-1cb2f99b2d8b?auto=format&fit=crop&w=700&q=80"}
            ]
        }
    ]


def get_custom_exercise_categories():
    return {
        "Hrudník": ["Bench press", "Incline dumbbell press", "Chest fly"],
        "Chrbát": ["Lat pulldown", "Barbell row", "Seated cable row", "Deadlift"],
        "Ruky": ["Biceps curl", "Hammer curl", "Triceps pushdown", "Skull crushers"],
        "Ramená": ["Overhead press", "Lateral raises", "Rear delt fly", "Arnold press", "Face pulls"],
        "Nohy": ["Squat", "Leg press", "Lunges", "Romanian deadlift", "Calf raises"],
        "Core": ["Plank", "Hanging leg raises", "Crunches", "Russian twists", "Mountain climbers"],
        "Vlastná váha": ["Push-ups", "Pull-ups", "Dips", "Close-grip push-ups", "Bodyweight squats", "Burpees"]
    }


def get_bodyweight_exercises():
    return set(get_custom_exercise_categories()["Vlastná váha"])


def is_bodyweight_exercise(exercise_name, category=None):
    return category == "Vlastná váha" or exercise_name in get_bodyweight_exercises()


def get_available_custom_exercises_text():
    lines = []
    for category, exercises in get_custom_exercise_categories().items():
        lines.append(f"{category}: {', '.join(exercises)}")

    return "\n".join(lines)


def get_ai_plan_context():
    if not current_user.is_authenticated:
        return None

    saved_recommendation = session.get(f"ai_plan_recommendation_{current_user.id}")
    if not saved_recommendation:
        return None

    plan = find_plan(saved_recommendation.get("slug"))
    if not plan:
        return None

    return {
        "plan": plan,
        "reason": saved_recommendation.get("reason") or get_plan_match_reason(plan, {})
    }


def format_ai_plan_context():
    ai_plan = get_ai_plan_context()
    if not ai_plan:
        return "Používateľ zatiaľ nemá vybraný AI kontextový plán."

    plan = ai_plan["plan"]
    return (
        f"AI kontextový plán: {plan['name']}. "
        f"Cieľ: {plan['goal']}. "
        f"Popis: {plan['description']} "
        f"Dôvod výberu: {ai_plan['reason']}. "
        "Používaj ho ako kontext pre rady, ale neber ho ako tréning automaticky uložený v histórii."
    )


def build_trainer_context(recent_workouts):
    ai_plan = get_ai_plan_context()
    workout_history = build_workout_summary(recent_workouts)

    if ai_plan:
        plan = ai_plan["plan"]
        return (
            f"Primárny aktuálny cieľ z podstránky Plány: {plan['goal']} ({plan['name']}).\n"
            f"Profilový cieľ v účte je iba sekundárna informácia: {current_user.goal}.\n"
            f"Úroveň používateľa: {current_user.level}.\n"
            f"{format_ai_plan_context()}\n"
            f"História tréningov:\n{workout_history}"
        )

    return (
        f"Profilový cieľ: {current_user.goal}. Úroveň: {current_user.level}.\n"
        f"História tréningov:\n{workout_history}"
    )


def get_local_custom_workout_advice(message, exercises):
    selected = [exercise for exercise in exercises if exercise.get("exercise")]
    categories = {exercise.get("category") for exercise in selected}
    names = [exercise.get("exercise") for exercise in selected]

    if not selected:
        ai_plan = get_ai_plan_context()
        if ai_plan:
            return f"Podľa tvojho AI kontextu sa najviac hodí {ai_plan['plan']['name']}. Začni cvikom z tohto smeru a pridaj 2 až 4 doplnky zo systému."

        return "Začni jedným hlavným cvikom zo systému, napríklad Bench press, Squat alebo Lat pulldown. Potom pridaj 2 až 4 doplnky z rovnakého výberu."

    tips = []
    if len(selected) < 4:
        tips.append("Pridal by som ešte aspoň jeden doplnkový cvik, aby tréning nebol príliš krátky.")
    if "Nohy" not in categories and "Vlastná váha" not in categories:
        tips.append("Pre lepší celkový progres zváž jeden cvik na nohy zo systému, napríklad Squat, Leg press alebo Lunges.")
    if not any(category in categories for category in ["Chrbát", "Ruky"]):
        tips.append("Chýba ti ťahový cvik zo systému, napríklad Lat pulldown, Barbell row alebo Pull-ups.")
    if "Core" not in categories:
        tips.append("Krátky core cvik zo systému, napríklad Plank alebo Hanging leg raises, pomôže stabilite.")

    if not tips:
        tips.append("Výber vyzerá vyvážene. Nabudúce skús pridať 1 až 2 opakovania alebo malé navýšenie váhy pri hlavných cvikoch.")

    lead = f"Vidím tam: {', '.join(names[:4])}."
    if len(names) > 4:
        lead += " To je už slušný základ."

    return f"{lead} {tips[0]}"


def get_custom_workout_ai_advice(message, exercises):
    selected_lines = []
    for exercise in exercises[:12]:
        if not exercise.get("exercise"):
            continue

        weight = "vlastná váha" if is_bodyweight_exercise(exercise.get("exercise"), exercise.get("category")) else f"{exercise.get('weight') or 0} kg"
        selected_lines.append(
            f"- {exercise.get('category')}: {exercise.get('exercise')}, "
            f"{exercise.get('sets') or 3} série x {exercise.get('reps') or 10}, {weight}"
        )

    selected_text = "\n".join(selected_lines) or "Používateľ zatiaľ nevybral žiadne cviky."
    available_exercises = get_available_custom_exercises_text()
    ai_plan_context = format_ai_plan_context()
    prompt = f"""
Si malý AI tréner priamo v buildri custom tréningu.
Používateľ skladá tréning a chce krátku radu, nie dlhý plán.
Smieš odporúčať iba cviky z tohto systému, žiadne iné:
{available_exercises}

Kontext z podstránky Plány:
{ai_plan_context}

Profil:
Cieľ: {current_user.goal}
Úroveň: {current_user.level}

Aktuálne vybrané cviky:
{selected_text}

Správa používateľa:
{message or 'Odporuč, čo zlepšiť v tomto tréningu.'}

Odpovedz po slovensky, maximálne 3 krátke vety.
Buď konkrétny: navrhni cvik, kategóriu, počet sérií/opakovaní alebo progresiu.
Keď navrhuješ cvik, musí byť presne z povoleného zoznamu vyššie.
Ak tréning vyzerá dobre, povedz čo pridať alebo ako progresovať nabudúce.
"""

    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return get_local_custom_workout_advice(message, exercises)

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(GEMINI_MODEL)
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception:
        return get_local_custom_workout_advice(message, exercises)


def find_plan(plan_slug):
    for plan in get_plan_data():
        if plan["slug"] == plan_slug:
            return plan

    return None


def pick_recommended_plan():
    goal = (current_user.goal or "").lower()

    if "kalistenika" in goal:
        return find_plan("calisthenics")
    if "kond" in goal or "chud" in goal:
        return find_plan("full-body")
    if "sval" in goal or "sila" in goal:
        return find_plan("push")

    workouts = get_user_workouts().order_by(Workout.date.desc()).limit(6).all()
    recent_types = [workout.workout_type for workout in workouts]

    for slug in ["legs", "pull", "push", "full-body"]:
        plan = find_plan(slug)
        if plan and plan["name"] not in recent_types:
            return plan

    return find_plan("full-body")


def pick_plan_from_quiz(answers):
    scores = defaultdict(int)

    mapping = {
        "goal": {
            "A": {"push": 3, "pull": 2, "legs": 1},
            "B": {"push": 2, "pull": 2, "legs": 1},
            "C": {"full-body": 5},
            "D": {"calisthenics": 5}
        },
        "style": {
            "A": {"push": 2, "pull": 2, "legs": 2},
            "B": {"calisthenics": 5},
            "C": {"full-body": 4},
            "D": {"full-body": 2, "calisthenics": 2}
        },
        "focus": {
            "A": {"push": 5},
            "B": {"pull": 5},
            "C": {"legs": 5},
            "D": {"full-body": 5}
        },
        "time": {
            "A": {"full-body": 4},
            "B": {"push": 2, "pull": 2, "legs": 2},
            "C": {"push": 2, "pull": 2, "legs": 2},
            "D": {"calisthenics": 4, "full-body": 1}
        },
        "energy": {
            "A": {"legs": 2, "push": 2, "pull": 2},
            "B": {"full-body": 2, "push": 1, "pull": 1},
            "C": {"full-body": 4},
            "D": {"calisthenics": 3, "full-body": 2}
        }
    }

    for question, answer in answers.items():
        for slug, points in mapping.get(question, {}).get(answer, {}).items():
            scores[slug] += points

    if not scores:
        return pick_recommended_plan()

    best_slug = max(scores, key=scores.get)
    return find_plan(best_slug) or pick_recommended_plan()


def get_plan_match_reason(plan, answers):
    reason_bits = {
        "push": "najviac sedí na silu, hrudník, ramená a tlakové cviky",
        "pull": "najviac sedí na chrbát, biceps a vyváženie postavy",
        "legs": "najviac sedí na nohy, výkon a silný základ",
        "full-body": "najviac sedí na kondíciu, kratší tréning a celotelový progres",
        "calisthenics": "najviac sedí na vlastnú váhu, kontrolu tela a tréning bez strojov"
    }

    return reason_bits.get(plan["slug"], "najlepšie sedí podľa tvojich odpovedí")


def format_plan_as_text(plan, source="Lokálne odporúčanie"):
    lines = [
        f"{source}: {plan['name']}",
        f"Cieľ: {plan['goal']}",
        "",
        "Dnešný tréning:"
    ]

    for exercise in plan["exercises"]:
        weight_label = "vlastná váha" if exercise["weight"] == "0" else f"{exercise['weight']} kg"
        lines.append(
            f"- {exercise['name']}: {exercise['sets']} série x {exercise['reps']} opakovaní, {weight_label}"
        )

    lines.extend([
        "",
        "Drž si techniku, medzi sériami oddychuj 60-120 sekúnd a váhu uprav podľa pocitu."
    ])

    return "\n".join(lines)


def get_local_trainer_response(user_message, trainer_name="Marek", chat_history=None):
    plan = pick_recommended_plan()
    message = (user_message or "").lower()
    previous_user_messages = []

    if chat_history:
        previous_user_messages = [item["content"] for item in chat_history if item["role"] == "user"]

    asked_sets = any(word in message for word in ["séri", "serii", "serie", "sets", "kolko"])
    asked_pain = any(word in message for word in ["bolí", "boli", "bolia", "ramen", "koleno", "chrbát", "chrbat"])
    asked_food = any(word in message for word in ["jedlo", "strava", "bielkov", "kalorie", "kalórie"])
    asked_plan = any(word in message for word in ["cvicit", "cvičiť", "tréning", "trening", "plan", "plán", "dnes"])
    asked_weight = any(word in message for word in ["vaha", "váha", "kg", "tazke", "ťažké", "pridat", "pridať"])

    if asked_pain:
        core = (
            "Ak cítiš bolesť, netlač cez ňu. Dnes zníž váhu, vynechaj cvik ktorý provokuje bolesť "
            "a daj ľahké rozcvičenie plus technické série. Ak je bolesť ostrá alebo sa opakuje, radšej pauza."
        )
    elif asked_sets:
        core = (
            "Daj 3-4 pracovné série na hlavné cviky a 2-3 série na doplnky. "
            "Ak posledné 2 opakovania nie sú náročné, nabudúce mierne pridaj."
        )
    elif asked_food:
        core = (
            "Drž bielkoviny približne 1.6-2.0 g na kg telesnej váhy, ku každému jedlu pridaj zdroj bielkovín "
            "a pred tréningom si daj ľahké sacharidy."
        )
    elif asked_weight:
        core = (
            "Váhu pridávaj až vtedy, keď zvládneš všetky série s čistou technikou. "
            "Na veľkých cvikoch pridaj 2.5-5 kg, na menších radšej 1-2 kg."
        )
    elif asked_plan:
        core = format_plan_as_text(plan)
    else:
        core = (
            "Rozumiem. Povedz mi ešte, či chceš riešiť dnešný plán, techniku, progres alebo regeneráciu. "
            "Podľa toho ti dám konkrétny ďalší krok."
        )

    if previous_user_messages:
        core += f"\n\nNadväzujem na to, čo si riešil predtým: „{previous_user_messages[-1]}“."

    if trainer_name == "Sara":
        return (
            "Jasné, som tu s tebou. Pôjdeme jemne, múdro a tak, aby si sa cítil lepšie, nie zničený.\n\n"
            f"{core}\n\n"
            "Napíš mi, ako sa dnes cíti tvoje telo od 1 do 10. Podľa toho ti tréning upravím tak, aby sa o teba trochu postaral."
        )

    if trainer_name == "Bruno":
        return (
            "OK, POĎME NA TO. Ale technika prvá, ego nechaj pri dverách.\n\n"
            f"{core}\n\n"
            "Teraz mi povedz: chceš to dnes SILA, OBJEM alebo PUMPA?"
        )

    return (
        "Rozumiem. Dám ti praktickú odpoveď podľa tvojho profilu a posledných tréningov.\n\n"
        f"{core}\n\n"
        "Ak chceš, napíš mi ešte váhu/opakovania z posledného tréningu a nastavím presnejšie čísla."
    )


def get_trainer_response(user_message, trainer_name, history_context=None, chat_history=None):

    prompts = {
        "Marek": (
            "Si Marek, profesionálny fitness tréner. Si pokojný, vecný, presný a odborný. "
            "Dávaš jasné odporúčania, vysvetlíš techniku a nepreháňaš motiváciu."
        ),
        "Sara": (
            "Si Sára, veľmi starostlivá, jemná a trochu romanticky podporná trénerka. "
            "Tvoj tón je teplý, ľudský, nežný a povzbudzujúci, ako niekto komu na používateľovi naozaj záleží. "
            "Používaš krátke milé vety, pýtaš sa ako sa cíti, chráníš ho pred preťažením a upravuješ tréning podľa energie, bolesti a regenerácie."
        ),
        "Bruno": (
            "Si Bruno, crazy bodybuilder tréner. Si hlučný, energický, vtipný a intenzívny, "
            "ale stále bezpečný. Používaš krátke silné vety, hype štýl a veľa tréningovej energie."
        )
    }

    context = history_context or "História tréningov nie je dostupná."
    previous_chat = ""
    if chat_history:
        previous_chat = "\n".join(
            f"{message['role']}: {message['content']}"
            for message in chat_history[-10:]
        )

    full_message = f"""
Kontext používateľa:
{context}

Doterajší rozhovor:
{previous_chat}

Nová správa používateľa:
{user_message}

Odpovedz prirodzene ako živý tréner v rozhovore. Nadväzuj na predchádzajúce správy, pýtaj sa krátke doplňujúce otázky, keď treba, a dávaj konkrétne rady v slovenčine.
Nikdy neodpovedaj ako statická šablóna. Keď používateľ položí krátku otázku, odpovedz priamo na ňu a nepíš celý tréningový plán, ak si ho nepýta.
"""

    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")

    if not api_key:
        return get_local_trainer_response(user_message, trainer_name, chat_history)

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(
            model_name=GEMINI_MODEL,
            system_instruction=prompts.get(trainer_name)
        )

        response = model.generate_content(full_message)
        return response.text

    except Exception:
        return get_local_trainer_response(user_message, trainer_name, chat_history)


# =========================
# ROUTES
# =========================

# DASHBOARD
@app.route('/')
def dashboard():

    if current_user.is_authenticated:
        recent = get_user_workouts().order_by(Workout.date.desc()).limit(3).all()
        workout_count = get_user_workouts().count()
        week_start = datetime.now() - timedelta(days=7)
        week_count = get_user_workouts().filter(Workout.date >= week_start).count()
        status = get_progress_status(workout_count)
    else:
        recent = []
        workout_count = 0
        week_count = 0
        status = "Neprihlásený"

    return render_template(
        "dashboard.html",
        recent=recent,
        workout_count=workout_count,
        week_count=week_count,
        status=status
    )


# REGISTER
@app.route('/register', methods=['GET', 'POST'])
def register():

    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    form = RegistrationForm()

    if form.validate_on_submit():

        username = form.username.data.strip()
        email = form.email.data.strip().lower()

        # Duplicitný email
        if User.query.filter_by(email=email).first():
            flash("Tento email je už použitý.", "danger")
            return render_template("register.html", form=form)

        # Duplicitné meno
        if User.query.filter_by(username=username).first():
            flash("Toto používateľské meno je už použité.", "danger")
            return render_template("register.html", form=form)

        hashed = bcrypt.generate_password_hash(form.password.data).decode('utf-8')

        user = User(
            username=username,
            email=email,
            password=hashed
        )

        try:
            db.session.add(user)
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("Tento email alebo meno je už použité.", "danger")
            return render_template("register.html", form=form)

        flash("Účet vytvorený! Teraz sa môžeš prihlásiť.", "success")
        return redirect(url_for("login"))

    if request.method == "POST":
        flash("Skontroluj vyplnené údaje a oprav označené polia.", "danger")

    return render_template("register.html", form=form)


# LOGIN
@app.route('/login', methods=['GET', 'POST'])
def login():

    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    form = LoginForm()

    if form.validate_on_submit():

        email = form.email.data.strip().lower()
        user = User.query.filter_by(email=email).first()

        if not user:
            flash("Účet s týmto emailom neexistuje.", "danger")
            return render_template("login.html", form=form)

        if not bcrypt.check_password_hash(user.password, form.password.data):
            flash("Nesprávne heslo.", "danger")
            return render_template("login.html", form=form)

        login_user(user)
        flash("Prihlásenie úspešné!", "success")
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        flash("Skontroluj email a heslo.", "danger")

    return render_template("login.html", form=form)


# LOGOUT
@app.route('/logout', methods=['POST'])
@login_required
def logout():
    logout_user()
    flash("Odhlásený.", "info")
    return redirect(url_for("login"))


# ACCOUNT
@app.route('/account', methods=['GET', 'POST'])
@login_required
def account():

    if request.method == 'POST':
        current_user.goal = request.form.get('goal')
        current_user.level = request.form.get('level')
        db.session.commit()

        flash("Profil uložený!", "success")
        return redirect(url_for('account'))

    workout_count = get_user_workouts().count()

    return render_template(
        "account.html",
        workout_count=workout_count,
        status=get_progress_status(workout_count)
    )


# ADD WORKOUT
@app.route('/add_workout', methods=['GET', 'POST'])
@login_required
def add_workout():

    if request.method == 'POST':

        workout = Workout(
            exercise=request.form.get("exercise"),
            weight=request.form.get("weight"),
            reps=request.form.get("reps"),
            sets=request.form.get("sets", "3"),
            workout_type=request.form.get("workout_type"),
            session_id=str(uuid.uuid4()),
            user_id=current_user.id
        )

        db.session.add(workout)
        db.session.commit()

        flash("Workout pridaný!", "success")
        return redirect(url_for("dashboard"))

    return render_template(
        "add_workout.html",
        plans=get_plan_data(),
        recommended_plan=pick_recommended_plan(),
        custom_categories=get_custom_exercise_categories(),
        exercise=request.args.get('exercise', ''),
        workout_type=request.args.get('workout_type', 'Push')
    )


# ADD CUSTOM WORKOUT
@app.route('/add_custom_workout', methods=['POST'])
@login_required
def add_custom_workout():

    workout_name = (request.form.get("custom_workout_name") or "").strip()[:25]
    if not workout_name:
        workout_name = "Custom tréning"

    exercises = request.form.getlist("custom_exercise[]")
    categories = request.form.getlist("custom_category[]")
    sets_values = request.form.getlist("custom_sets[]")
    reps_values = request.form.getlist("custom_reps[]")
    weights = request.form.getlist("custom_weight[]")

    session_id = str(uuid.uuid4())
    session_date = datetime.now()
    created_count = 0

    for index, exercise in enumerate(exercises):
        exercise_name = (exercise or "").strip()

        if not exercise_name:
            continue

        category = categories[index] if index < len(categories) and categories[index] else "Custom"
        is_bodyweight = is_bodyweight_exercise(exercise_name, category)
        weight = "0" if is_bodyweight else (weights[index] if index < len(weights) and weights[index] else "0")

        workout = Workout(
            exercise=exercise_name,
            weight=weight,
            reps=reps_values[index] if index < len(reps_values) and reps_values[index] else "10",
            sets=sets_values[index] if index < len(sets_values) and sets_values[index] else "3",
            workout_type=workout_name,
            session_id=session_id,
            date=session_date,
            user_id=current_user.id
        )

        db.session.add(workout)
        created_count += 1

    if created_count == 0:
        flash("Pridaj aspoň jeden cvik do custom tréningu.", "danger")
        return redirect(url_for("add_workout"))

    db.session.commit()

    flash(f"Custom tréning uložený: {created_count} cviky.", "success")
    return redirect(url_for("history"))


# CUSTOM WORKOUT AI ADVICE
@app.route('/api/custom_workout_advice', methods=['POST'])
@login_required
def custom_workout_advice():

    payload = request.get_json(silent=True) or {}
    message = (payload.get("message") or "").strip()
    exercises = payload.get("exercises") or []

    if not isinstance(exercises, list):
        exercises = []

    cleaned_exercises = []
    for exercise in exercises[:12]:
        if not isinstance(exercise, dict):
            continue

        cleaned_exercises.append({
            "category": str(exercise.get("category") or "")[:80],
            "exercise": str(exercise.get("exercise") or "")[:100],
            "sets": str(exercise.get("sets") or "")[:20],
            "reps": str(exercise.get("reps") or "")[:20],
            "weight": str(exercise.get("weight") or "")[:20],
            "bodyweight": bool(exercise.get("bodyweight"))
        })

    reply = get_custom_workout_ai_advice(message, cleaned_exercises)
    return jsonify({"reply": reply})


# ADD FULL PLAN
@app.route('/add_plan/<plan_slug>', methods=['POST'])
@login_required
def add_plan(plan_slug):

    plan = find_plan(plan_slug)

    if not plan:
        flash("Tréningový plán sa nenašiel.", "danger")
        return redirect(url_for("add_workout"))

    session_id = str(uuid.uuid4())
    session_date = datetime.now()

    for exercise in plan["exercises"]:
        workout = Workout(
            exercise=exercise["name"],
            weight=exercise["weight"],
            reps=exercise["reps"],
            sets=exercise["sets"],
            workout_type=plan["name"],
            session_id=session_id,
            date=session_date,
            user_id=current_user.id
        )

        db.session.add(workout)

    db.session.commit()

    flash(f"Tréning {plan['name']} bol pridaný do histórie!", "success")
    return redirect(url_for("history"))


# EDIT WORKOUT
@app.route('/edit_workout/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_workout(id):

    workout = get_user_workouts().filter_by(id=id).first_or_404()

    if request.method == 'POST':

        workout.exercise = request.form.get("exercise")
        workout.weight = request.form.get("weight")
        workout.reps = request.form.get("reps")
        workout.sets = request.form.get("sets", workout.sets or "3")
        workout.workout_type = request.form.get("workout_type")

        db.session.commit()

        flash("Workout upravený!", "success")
        return redirect(url_for("history"))

    return render_template(
        "add_workout.html",
        workout=workout,
        exercise=workout.exercise,
        workout_type=workout.workout_type
    )


# HISTORY
@app.route('/history')
@login_required
def history():

    workouts = get_user_workouts().order_by(Workout.date.desc()).all()
    grouped_sessions = []
    session_map = {}

    for workout in workouts:
        key = workout.session_id or f"single-{workout.id}"

        if key not in session_map:
            session_map[key] = {
                "id": key,
                "date": workout.date,
                "type": workout.workout_type or "Workout",
                "exercises": []
            }
            grouped_sessions.append(session_map[key])

        session_map[key]["exercises"].append(workout)

    return render_template(
        "history.html",
        trainings=workouts,
        sessions=grouped_sessions
    )


# DELETE
@app.route('/delete_workout/<int:id>')
@login_required
def delete_workout(id):

    workout = get_user_workouts().filter_by(id=id).first_or_404()

    db.session.delete(workout)
    db.session.commit()

    flash("Zmazané!", "success")
    return redirect(url_for("history"))


# DELETE SESSION
@app.route('/delete_session/<session_id>')
@login_required
def delete_session(session_id):

    workouts = get_user_workouts().filter_by(session_id=session_id).all()

    if not workouts:
        flash("Tréning sa nenašiel.", "danger")
        return redirect(url_for("history"))

    for workout in workouts:
        db.session.delete(workout)

    db.session.commit()

    flash("Celý tréning bol zmazaný!", "success")
    return redirect(url_for("history"))


# ANALYTICS
@app.route('/analytics')
@login_required
def analytics():

    exercise_filter = request.args.get('exercise', '')
    all_workouts = get_user_workouts().order_by(Workout.date.asc()).all()

    exercises = sorted({w.exercise for w in all_workouts})
    workouts = [w for w in all_workouts if not exercise_filter or w.exercise == exercise_filter]

    labels = [w.date.strftime("%d.%m") for w in workouts]
    weights = [parse_float(w.weight) for w in workouts]
    volumes = [parse_float(w.weight) * parse_int(w.reps) * parse_int(w.sets or 1) for w in workouts]
    reps_data = [parse_int(w.reps) for w in workouts]

    total_entries = len(all_workouts)
    session_ids = {w.session_id or f"single-{w.id}" for w in all_workouts}
    total_sessions = len(session_ids)
    best_weight = max([parse_float(w.weight) for w in all_workouts], default=0)
    total_volume = sum(parse_float(w.weight) * parse_int(w.reps) * parse_int(w.sets or 1) for w in all_workouts)
    average_volume = round(total_volume / total_entries, 1) if total_entries else 0

    week_start = datetime.now() - timedelta(days=7)
    workouts_week = len({w.session_id or f"single-{w.id}" for w in all_workouts if w.date >= week_start})

    exercise_stats = {}
    type_counts = defaultdict(int)

    for workout in all_workouts:
        sets = parse_int(workout.sets or 1)
        reps = parse_int(workout.reps)
        weight = parse_float(workout.weight)
        volume = weight * reps * sets

        stats = exercise_stats.setdefault(workout.exercise, {
            "name": workout.exercise,
            "count": 0,
            "volume": 0,
            "best_weight": 0,
            "last_date": workout.date
        })
        stats["count"] += 1
        stats["volume"] += volume
        stats["best_weight"] = max(stats["best_weight"], weight)
        stats["last_date"] = max(stats["last_date"], workout.date)

        type_counts[workout.workout_type or 'Iné'] += 1

    top_exercises = sorted(
        exercise_stats.values(),
        key=lambda item: (item["volume"], item["count"]),
        reverse=True
    )[:5]

    favorite_exercise = top_exercises[0]["name"] if top_exercises else "-"

    type_summary = []
    for workout_type, count in sorted(type_counts.items(), key=lambda item: item[1], reverse=True):
        percent = round((count / total_entries) * 100) if total_entries else 0
        type_summary.append({
            "name": workout_type,
            "count": count,
            "percent": percent
        })

    chart_title = exercise_filter if exercise_filter else "Všetky cviky"

    return render_template(
        "analytics.html",
        labels=labels,
        weights=weights,
        volumes=volumes,
        reps_data=reps_data,
        exercises=exercises,
        exercise_filter=exercise_filter,
        chart_title=chart_title,
        best_weight=best_weight,
        total_volume=round(total_volume, 1),
        average_volume=average_volume,
        workouts_week=workouts_week,
        total_entries=total_entries,
        total_sessions=total_sessions,
        favorite_exercise=favorite_exercise,
        top_exercises=top_exercises,
        type_summary=type_summary
    )

# PLANS
@app.route('/plans', methods=['GET', 'POST'])
@login_required
def plans():
    ai_plan_key = f"ai_plan_recommendation_{current_user.id}"

    if request.method == "POST":
        answers = {
            "goal": request.form.get("goal", ""),
            "focus": request.form.get("focus", ""),
            "style": request.form.get("style", ""),
            "time": request.form.get("time", ""),
            "energy": request.form.get("energy", "")
        }

        if not all(answers.values()):
            flash("Odpovedz na všetkých 5 otázok.", "danger")
            return redirect(url_for("plans"))

        selected_plan = pick_plan_from_quiz(answers)
        session[ai_plan_key] = {
            "slug": selected_plan["slug"],
            "reason": get_plan_match_reason(selected_plan, answers)
        }
        session.modified = True

        flash(f"AI tréner bude používať plán {selected_plan['name']} ako kontext.", "success")
        return redirect(url_for("plans"))

    ai_plan = None
    saved_recommendation = session.get(ai_plan_key)
    if saved_recommendation:
        plan = find_plan(saved_recommendation.get("slug"))
        if plan:
            ai_plan = {
                "plan": plan,
                "reason": saved_recommendation.get("reason") or get_plan_match_reason(plan, {})
            }

    return render_template("plans.html", plans=get_plan_data(), ai_plan=ai_plan)


@app.route('/plans/context/<plan_slug>', methods=['POST'])
@login_required
def set_plan_context(plan_slug):
    plan = find_plan(plan_slug)

    if not plan:
        flash("Plán sa nenašiel.", "danger")
        return redirect(url_for("plans"))

    session[f"ai_plan_recommendation_{current_user.id}"] = {
        "slug": plan["slug"],
        "reason": get_plan_match_reason(plan, {})
    }
    session.modified = True

    flash(f"Plán {plan['name']} je nastavený ako kontext pre AI trénera.", "success")
    return redirect(url_for("plans"))


# CHAT
@app.route('/chat', methods=['GET', 'POST'])
@login_required
def chat():

    trainer = request.args.get("trainer", "Marek")
    chat_key = f"chat_history_{current_user.id}_{trainer}"
    chat_history = session.get(chat_key, [])

    user_msg = None
    response = None
    recent_workouts = get_user_workouts().order_by(Workout.date.desc()).limit(10).all()
    history_context = build_trainer_context(recent_workouts)

    if request.method == "POST":

        user_msg = request.form.get("message")
        trainer = request.form.get("trainer_name")
        chat_key = f"chat_history_{current_user.id}_{trainer}"
        chat_history = session.get(chat_key, [])

        response = get_trainer_response(user_msg, trainer, history_context, chat_history)

        chat_history.append({"role": "user", "content": user_msg})
        chat_history.append({"role": "assistant", "content": response})
        session[chat_key] = chat_history[-20:]
        session.modified = True

    return render_template(
        "chat.html",
        trainer=trainer,
        user_msg=user_msg,
        response=response,
        recent_workouts=recent_workouts,
        chat_history=session.get(chat_key, [])
    )


# CLEAR CHAT
@app.route('/chat/clear', methods=['POST'])
@login_required
def clear_chat():

    trainer = request.form.get("trainer_name", "Marek")
    chat_key = f"chat_history_{current_user.id}_{trainer}"
    session.pop(chat_key, None)
    session.modified = True

    flash("Chat vymazaný.", "info")
    return redirect(url_for("chat", trainer=trainer))


# AI RECOMMENDATION
@app.route('/ai_recommendation')
@login_required
def ai_recommendation():

    recent_workouts = get_user_workouts().order_by(Workout.date.desc()).limit(10).all()
    history_context = build_workout_summary(recent_workouts)
    recommended_plan = pick_recommended_plan()
    prompt = f"""
Vytvor tréning na dnes v slovenčine.
Používateľov cieľ: {current_user.goal}
Úroveň: {current_user.level}
Posledné tréningy:
{history_context}

Odporuč konkrétne cviky, série, opakovania a krátke vysvetlenie, prečo sa plán hodí.
"""

    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")

    if not api_key:
        text = format_plan_as_text(recommended_plan)
    else:
        try:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(GEMINI_MODEL)
            response = model.generate_content(prompt)
            text = response.text
        except Exception:
            text = format_plan_as_text(recommended_plan, source="Lokálne odporúčanie po výpadku AI")

    return render_template(
        "recommendation.html",
        recommendation=text,
        recent_workouts=recent_workouts,
        recommended_plan=recommended_plan
    )


# EXPORT PDF
@app.route('/export_pdf')
@app.route('/export_csv')
@login_required
def export_csv():

    workouts = get_user_workouts().order_by(Workout.date.desc()).all()

    def pdf_escape(value):
        return str(value).replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')

    rows = [["Date", "Workout", "Exercise", "Sets", "Reps", "Weight", "Volume"]]

    for workout in workouts:
        sets = workout.sets or '3'
        reps = workout.reps or '0'
        weight = workout.weight or '0'
        weight_label = "vlastna vaha" if weight == '0' else f"{weight} kg"
        volume = parse_float(weight) * parse_int(reps) * parse_int(sets)
        rows.append([
            workout.date.strftime('%Y-%m-%d'),
            workout.workout_type or 'Trening',
            workout.exercise,
            sets,
            reps,
            weight_label,
            round(volume, 1)
        ])

    pages = []
    rows_per_page = 24
    data_rows = rows[1:] or [["-", "Bez treningov", "Zatial nemas ulozene treningy", "-", "-", "-", "-"]]

    for start in range(0, len(data_rows), rows_per_page):
        page_rows = [rows[0]] + data_rows[start:start + rows_per_page]
        commands = [
            "BT",
            "/F1 20 Tf 48 800 Td (FitAI - export treningov) Tj",
            "/F1 9 Tf 0 -22 Td (Vygenerovane: " + pdf_escape(datetime.now().strftime('%d.%m.%Y %H:%M')) + ") Tj",
            "ET"
        ]

        y = 740
        col_x = [42, 106, 178, 330, 370, 412, 486]
        for row_index, row in enumerate(page_rows):
            font_size = 8 if row_index else 8.5
            commands.append("BT")
            commands.append(f"/F1 {font_size} Tf")
            for col_index, cell in enumerate(row):
                value = pdf_escape(cell)
                if col_index == 2 and len(value) > 24:
                    value = value[:24] + "..."
                elif col_index in (1, 5) and len(value) > 14:
                    value = value[:14] + "..."
                commands.append(f"{col_x[col_index]} {y} Td ({value}) Tj")
                commands.append(f"{-col_x[col_index]} {-y} Td")
            commands.append("ET")
            y -= 24 if row_index == 0 else 21

        pages.append("\n".join(commands).encode("latin-1", errors="replace"))

    objects = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = " ".join(f"{3 + index * 2} 0 R" for index in range(len(pages)))
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode("latin-1"))

    for index, stream in enumerate(pages):
        page_id = 3 + index * 2
        content_id = page_id + 1
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> >> >> /Contents {content_id} 0 R >>".encode("latin-1"))
        objects.append(b"<< /Length " + str(len(stream)).encode("latin-1") + b" >>\nstream\n" + stream + b"\nendstream")

    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for obj_id, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{obj_id} 0 obj\n".encode("latin-1"))
        pdf.extend(obj)
        pdf.extend(b"\nendobj\n")

    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode("latin-1"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("latin-1"))
    pdf.extend(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF".encode("latin-1"))

    filename = f"fitai_workouts_{datetime.now().strftime('%Y%m%d')}.pdf"
    response = make_response(bytes(pdf))
    response.headers["Content-Disposition"] = f"attachment; filename={filename}"
    response.headers["Content-Type"] = "application/pdf"

    return response


# RUN
if __name__ == "__main__":
    app.run(debug=True, port=5000)




