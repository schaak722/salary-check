import os
import datetime

import csv
from pathlib import Path

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
)
from flask_sqlalchemy import SQLAlchemy

# -------------------------------------------------
# Config
# -------------------------------------------------

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret")

# Basic auth config (change these in env vars for real use)
app.config["ADMIN_USERNAME"] = os.environ.get("ADMIN_USERNAME", "admin")
app.config["ADMIN_PASSWORD"] = os.environ.get("ADMIN_PASSWORD", "Salary26?")

# Example: postgres://user:pass@host:port/dbname
database_url = os.environ.get("DATABASE_URL", "sqlite:///salary_db.sqlite3")
app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


# -------------------------------------------------
# Models
# -------------------------------------------------

class JobTitle(db.Model):
    __tablename__ = "job_titles"

    id = db.Column(db.Integer, primary_key=True)
    canonical_title = db.Column(db.String(255), unique=True, nullable=False)
    category = db.Column(db.String(100), nullable=False)
    seniority_level = db.Column(db.String(50), nullable=False)  # Entry, Mid, Senior, Manager, C-Level
    aliases = db.Column(db.Text, nullable=True)  # pipe-separated aliases

    salary_bands = db.relationship("SalaryBand", back_populates="job_title")

    def __repr__(self):
        return f"<JobTitle {self.canonical_title}>"


class ExperienceBand(db.Model):
    __tablename__ = "experience_bands"

    code = db.Column(db.String(10), primary_key=True)  # JNR, MID, SNR, LDR, TRN
    label = db.Column(db.String(100), nullable=False)
    min_years = db.Column(db.Integer, nullable=True)
    max_years = db.Column(db.Integer, nullable=True)
    default_seniority_level = db.Column(db.String(50), nullable=True)
    description = db.Column(db.Text, nullable=True)

    salary_bands = db.relationship("SalaryBand", back_populates="experience_band")

    def __repr__(self):
        return f"<ExperienceBand {self.code}>"


class SalaryBand(db.Model):
    __tablename__ = "salary_bands"

    id = db.Column(db.Integer, primary_key=True)

    job_title_id = db.Column(db.Integer, db.ForeignKey("job_titles.id"), nullable=False)
    experience_band_code = db.Column(
        db.String(10),
        db.ForeignKey("experience_bands.code"),
        nullable=False,
    )

    location = db.Column(db.String(100), nullable=False, default="Malta")
    industry = db.Column(db.String(100), nullable=True)
    company_size_band = db.Column(db.String(50), nullable=True)  # eg "1-10", "11-50"
    currency = db.Column(db.String(10), nullable=False, default="EUR")

    salary_min = db.Column(db.Numeric(12, 2), nullable=True)
    salary_max = db.Column(db.Numeric(12, 2), nullable=True)
    salary_avg = db.Column(db.Numeric(12, 2), nullable=True)

    sample_size = db.Column(db.Integer, nullable=True)
    source_type = db.Column(db.String(100), nullable=True)       # "Employer-reported", etc.
    confidence_level = db.Column(db.String(20), nullable=True)   # "Low", "Medium", "High"

    last_updated = db.Column(
        db.Date,
        nullable=False,
        default=datetime.date.today,
    )
    notes = db.Column(db.Text, nullable=True)

    job_title = db.relationship("JobTitle", back_populates="salary_bands")
    experience_band = db.relationship("ExperienceBand", back_populates="salary_bands")

    def __repr__(self):
        return f"<SalaryBand {self.job_title.canonical_title} {self.experience_band_code}>"


# -------------------------------------------------
# CLI helper to create tables once
# -------------------------------------------------

@app.cli.command("init-db")
def init_db():
    """Create all tables."""
    db.create_all()
    print("✅ Database tables created.")

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"


@app.cli.command("seed-experience-bands")
def seed_experience_bands():
    """Seed experience_bands table from data/experience_bands.csv"""
    csv_path = DATA_DIR / "experience_bands.csv"
    if not csv_path.exists():
        print(f"❌ {csv_path} not found")
        return

    def to_int(val):
        val = (val or "").strip()
        if val == "":
            return None
        try:
            return int(val)
        except ValueError:
            return None

    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        count = 0
        for row in reader:
            code = (row.get("experience_band_code") or "").strip()
            if not code:
                continue

            # Skip if already exists
            existing = ExperienceBand.query.get(code)
            if existing:
                continue

            band = ExperienceBand(
                code=code,
                label=(row.get("label") or "").strip(),
                min_years=to_int(row.get("min_years")),
                max_years=to_int(row.get("max_years")),
                default_seniority_level=(row.get("default_seniority_level") or "").strip() or None,
                description=(row.get("description") or "").strip() or None,
            )
            db.session.add(band)
            count += 1

        db.session.commit()
    print(f"✅ Seeded {count} experience bands from {csv_path.name}")

@app.cli.command("seed-job-titles")
def seed_job_titles():
    """Seed job_titles table from data/job_titles_malta_master.csv"""
    csv_path = DATA_DIR / "job_titles_malta_master.csv"
    if not csv_path.exists():
        print(f"❌ {csv_path} not found")
        return

    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        count_new = 0
        for row in reader:
            canonical_title = row["canonical_title"].strip()
            if not canonical_title:
                continue

            existing = JobTitle.query.filter_by(canonical_title=canonical_title).first()
            if existing:
                continue

            jt = JobTitle(
                canonical_title=canonical_title,
                category=row["category"].strip(),
                seniority_level=row["seniority_level"].strip(),
                aliases=(row.get("aliases") or "").strip() or None,
            )
            db.session.add(jt)
            count_new += 1

        db.session.commit()
    print(f"✅ Seeded {count_new} job titles from {csv_path.name}")

# -------------------------------------------------
# Routes
# -------------------------------------------------

def login_required(view_func):
    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        if not session.get("user"):
            return redirect(url_for("login", next=request.path))
        return view_func(*args, **kwargs)
    return wrapped_view
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = (request.form.get("password") or "").strip()

        if (
            username == app.config["ADMIN_USERNAME"]
            and password == app.config["ADMIN_PASSWORD"]
        ):
            session["user"] = username
            flash("Logged in successfully.", "success")
            next_url = request.args.get("next") or url_for("index")
            return redirect(next_url)
        else:
            flash("Invalid username or password.", "danger")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop("user", None)
    flash("Logged out.", "success")
    return redirect(url_for("login"))


@app.route("/")
@login_required
def index():
    return render_template("index.html")


@app.route("/job-titles")
@login_required
def job_titles_list():
    search = request.args.get("q", "").strip()
    query = JobTitle.query

    if search:
        like = f"%{search}%"
        query = query.filter(JobTitle.canonical_title.ilike(like))

    job_titles = query.order_by(JobTitle.category, JobTitle.canonical_title).all()
    return render_template("job_titles.html", job_titles=job_titles, search=search)


@app.route("/salary-bands")
@login_required
def salary_bands_list():
    job_title_id = request.args.get("job_title_id")
    experience_code = request.args.get("experience_band_code")

    query = SalaryBand.query.join(JobTitle).join(ExperienceBand)

    if job_title_id:
        query = query.filter(SalaryBand.job_title_id == int(job_title_id))

    if experience_code:
        query = query.filter(SalaryBand.experience_band_code == experience_code)

    salary_bands = query.order_by(JobTitle.canonical_title, SalaryBand.experience_band_code).all()
    job_titles = JobTitle.query.order_by(JobTitle.canonical_title).all()
    experience_bands = ExperienceBand.query.order_by(ExperienceBand.min_years).all()

    return render_template(
        "salary_bands.html",
        salary_bands=salary_bands,
        job_titles=job_titles,
        experience_bands=experience_bands,
        selected_job_title_id=job_title_id,
        selected_experience_code=experience_code,
    )


@app.route("/salary-bands/new", methods=["GET", "POST"])
@login_required
def salary_band_new():
    job_titles = JobTitle.query.order_by(JobTitle.canonical_title).all()
    experience_bands = ExperienceBand.query.order_by(ExperienceBand.min_years).all()

    if request.method == "POST":
        job_title_id = request.form.get("job_title_id")
        experience_band_code = request.form.get("experience_band_code")
        location = request.form.get("location") or "Malta"
        industry = request.form.get("industry") or None
        company_size_band = request.form.get("company_size_band") or None
        currency = request.form.get("currency") or "EUR"
        salary_min = request.form.get("salary_min") or None
        salary_max = request.form.get("salary_max") or None
        salary_avg = request.form.get("salary_avg") or None
        sample_size = request.form.get("sample_size") or None
        source_type = request.form.get("source_type") or None
        confidence_level = request.form.get("confidence_level") or None
        notes = request.form.get("notes") or None

        if not job_title_id or not experience_band_code:
            flash("Job title and experience band are required.", "danger")
            return render_template(
                "salary_band_form.html",
                job_titles=job_titles,
                experience_bands=experience_bands,
            )

        def make_decimal(value):
            if not value:
                return None
            try:
                return float(value)
            except ValueError:
                return None

        salary_band = SalaryBand(
            job_title_id=int(job_title_id),
            experience_band_code=experience_band_code,
            location=location,
            industry=industry,
            company_size_band=company_size_band,
            currency=currency,
            salary_min=make_decimal(salary_min),
            salary_max=make_decimal(salary_max),
            salary_avg=make_decimal(salary_avg),
            sample_size=int(sample_size) if sample_size else None,
            source_type=source_type,
            confidence_level=confidence_level,
            notes=notes,
            last_updated=datetime.date.today(),
        )

        db.session.add(salary_band)
        db.session.commit()
        flash("Salary band created.", "success")
        return redirect(url_for("salary_bands_list"))

    return render_template(
        "salary_band_form.html",
        job_titles=job_titles,
        experience_bands=experience_bands,
    )


if __name__ == "__main__":
    app.run(debug=True)
