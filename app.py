from flask import Flask, flash, redirect, render_template, request, url_for
from flask_socketio import SocketIO
from flask_login import (
    LoginManager,
    UserMixin,
    current_user,
    login_required,
    login_user,
    logout_user,
)
import re
import sqlite3
from datetime import datetime
from werkzeug.security import check_password_hash, generate_password_hash

ESTOQUE_BAIXO_LIMITE = 5

app = Flask(__name__)
app.secret_key = "maison-lumiere-secret-key"

socketio = SocketIO(app, cors_allowed_origins="*")

login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.login_message = "Faça login para acessar esta área."
login_manager.login_message_category = "warning"
login_manager.init_app(app)


def conectar():
    conn = sqlite3.connect("loja_velas.db")
    conn.row_factory = sqlite3.Row
    return conn


class Usuario(UserMixin):
    def __init__(self, user_id, nome, email):
        self.id = str(user_id)
        self.nome = nome
        self.email = email


@login_manager.user_loader
def carregar_usuario(user_id):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("SELECT id, nome, email FROM usuario WHERE id = ?", (user_id,))
    registro = cursor.fetchone()
    conn.close()

    if registro:
        return Usuario(registro["id"], registro["nome"], registro["email"])
    return None


@app.route("/")
@login_required
def home():
    return render_template("index.html")


@app.route("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("home"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        senha = request.form.get("senha", "")

        conn = conectar()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM usuario WHERE email = ?", (email,))
        usuario = cursor.fetchone()
        conn.close()

        if usuario and check_password_hash(usuario["senha_hash"], senha):
            login_user(Usuario(usuario["id"], usuario["nome"], usuario["email"]))
            return redirect(url_for("home"))

        flash("Email ou senha inválidos.", "danger")

    return render_template("login.html")


@app.route("/cadastro", methods=["GET", "POST"])
def cadastro():
    if request.method == "POST":
        nome = request.form.get("nome", "")
        email = request.form.get("email", "").lower()
        senha = request.form.get("senha", "")

        conn = conectar()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM usuario WHERE email = ?", (email,))
        if cursor.fetchone():
            flash("Email já cadastrado.", "warning")
            return render_template("cadastro.html")

        senha_hash = generate_password_hash(senha)
        cursor.execute(
            "INSERT INTO usuario (nome, email, senha_hash) VALUES (?, ?, ?)",
            (nome, email, senha_hash),
        )
        conn.commit()
        conn.close()

        flash("Cadastro realizado!", "success")
        return redirect("/login")

    return render_template("cadastro.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect("/login")


@socketio.on("message")
def handle_message(msg):
    print("Mensagem:", msg)


if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=10000)
