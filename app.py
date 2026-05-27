from flask import Flask, flash, redirect, render_template, request, url_for
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

login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.login_message = "Faça login para acessar esta área."
login_manager.login_message_category = "warning"
login_manager.init_app(app)

# conexão com banco
def conectar():
    conn = sqlite3.connect("loja_velas.db")
    conn.row_factory = sqlite3.Row
    return conn


def garantir_tabela_usuarios():
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS usuario (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            senha_hash TEXT NOT NULL
        )
        """
    )
    cursor.execute("PRAGMA table_info(usuario)")
    colunas = {coluna[1] for coluna in cursor.fetchall()}

    if "nome" not in colunas:
        cursor.execute("ALTER TABLE usuario ADD COLUMN nome TEXT")
    if "email" not in colunas:
        cursor.execute("ALTER TABLE usuario ADD COLUMN email TEXT")
    if "senha_hash" not in colunas:
        cursor.execute("ALTER TABLE usuario ADD COLUMN senha_hash TEXT")

    # Compatibilidade com schema legado: usuario/senha -> nome/email/senha_hash
    cursor.execute(
        """
        UPDATE usuario
        SET nome = COALESCE(NULLIF(nome, ''), usuario)
        WHERE nome IS NULL OR nome = ''
        """
    )
    cursor.execute(
        """
        UPDATE usuario
        SET email = LOWER(
            REPLACE(COALESCE(NULLIF(nome, ''), 'usuario'), ' ', '') || id || '@local.maison'
        )
        WHERE email IS NULL OR email = ''
        """
    )

    if "senha" in colunas:
        cursor.execute("SELECT id, senha FROM usuario WHERE (senha_hash IS NULL OR senha_hash = '')")
        registros = cursor.fetchall()
        for registro in registros:
            senha_legada = registro["senha"] or ""
            if senha_legada:
                cursor.execute(
                    "UPDATE usuario SET senha_hash = ? WHERE id = ?",
                    (generate_password_hash(senha_legada), registro["id"]),
                )

    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_usuario_email ON usuario(email)")
    conn.commit()
    conn.close()


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


def formatar_preco(valor):
    try:
        numero = float(str(valor).replace(",", "."))
    except (TypeError, ValueError):
        return str(valor)
    texto = f"{numero:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {texto}"


def status_estoque(estoque):
    try:
        qtd = int(estoque)
    except (TypeError, ValueError):
        qtd = 0
    if qtd <= 0:
        return "sem", "Sem estoque", "badge-estoque-sem"
    if qtd <= ESTOQUE_BAIXO_LIMITE:
        return "baixo", "Estoque baixo", "badge-estoque-baixo"
    return "ok", "Em estoque", "badge-estoque-ok"


def enriquecer_produto(registro):
    codigo, rotulo, classe = status_estoque(registro["estoque"])
    return {
        "id": registro["id"],
        "nome": registro["nome"],
        "aroma": registro["aroma"],
        "preco": registro["preco"],
        "preco_formatado": formatar_preco(registro["preco"]),
        "estoque": registro["estoque"],
        "status_codigo": codigo,
        "status_rotulo": rotulo,
        "status_classe": classe,
    }


def validar_produto_form(nome, aroma, preco, estoque):
    erros = []
    nome = (nome or "").strip()
    aroma = (aroma or "").strip()
    preco_txt = (preco or "").strip()
    estoque_txt = (estoque or "").strip()

    if len(nome) < 2:
        erros.append("Informe um nome com pelo menos 2 caracteres.")
    if len(aroma) < 2:
        erros.append("Informe um aroma valido.")

    preco_num = None
    if not preco_txt:
        erros.append("Informe o preco do produto.")
    else:
        if not re.fullmatch(r"\d+([.,]\d{1,2})?", preco_txt):
            erros.append("Preco invalido. Use formato como 29.90 ou 29,90.")
        else:
            preco_num = float(preco_txt.replace(",", "."))
            if preco_num <= 0:
                erros.append("O preco deve ser maior que zero.")

    estoque_num = None
    if not estoque_txt:
        erros.append("Informe a quantidade em estoque.")
    else:
        if not re.fullmatch(r"\d+", estoque_txt):
            erros.append("Estoque invalido. Use apenas numeros inteiros.")
        else:
            estoque_num = int(estoque_txt)
            if estoque_num < 0:
                erros.append("O estoque nao pode ser negativo.")

    dados = {
        "nome": nome,
        "aroma": aroma,
        "preco": preco_num,
        "estoque": estoque_num,
    }
    return len(erros) == 0, erros, dados


def buscar_produtos(termo_busca=""):
    conn = conectar()
    cursor = conn.cursor()
    termo = (termo_busca or "").strip()

    if termo:
        like = f"%{termo}%"
        cursor.execute(
            """
            SELECT * FROM produto
            WHERE nome LIKE ? OR aroma LIKE ?
            ORDER BY nome COLLATE NOCASE
            """,
            (like, like),
        )
    else:
        cursor.execute("SELECT * FROM produto ORDER BY nome COLLATE NOCASE")

    registros = cursor.fetchall()
    conn.close()
    return [enriquecer_produto(r) for r in registros]


def obter_produto_por_id(produto_id):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM produto WHERE id = ?", (produto_id,))
    registro = cursor.fetchone()
    conn.close()
    return registro


def garantir_tabela_clientes():
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS cliente (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            email TEXT NOT NULL,
            telefone TEXT NOT NULL,
            cidade TEXT NOT NULL
        )
        """
    )
    cursor.execute("PRAGMA table_info(cliente)")
    colunas = {coluna[1] for coluna in cursor.fetchall()}

    if "telefone" not in colunas:
        cursor.execute("ALTER TABLE cliente ADD COLUMN telefone TEXT")
    if "cidade" not in colunas:
        cursor.execute("ALTER TABLE cliente ADD COLUMN cidade TEXT")

    cursor.execute(
        """
        UPDATE cliente
        SET telefone = COALESCE(NULLIF(telefone, ''), 'Nao informado')
        WHERE telefone IS NULL OR telefone = ''
        """
    )
    cursor.execute(
        """
        UPDATE cliente
        SET cidade = COALESCE(NULLIF(cidade, ''), 'Nao informada')
        WHERE cidade IS NULL OR cidade = ''
        """
    )

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_cliente_nome ON cliente(nome)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_cliente_email ON cliente(email)")
    conn.commit()
    conn.close()


def validar_cliente_form(nome, email, telefone, cidade, cliente_id=None):
    erros = []
    nome = (nome or "").strip()
    email = (email or "").strip().lower()
    telefone = (telefone or "").strip()
    cidade = (cidade or "").strip()

    if len(nome) < 2:
        erros.append("Informe um nome com pelo menos 2 caracteres.")

    if not email:
        erros.append("Informe o email do cliente.")
    elif not re.fullmatch(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        erros.append("Informe um email valido.")

    telefone_limpo = re.sub(r"\D", "", telefone)
    if not telefone:
        erros.append("Informe o telefone do cliente.")
    elif len(telefone_limpo) < 10:
        erros.append("Informe um telefone valido com DDD.")

    if len(cidade) < 2:
        erros.append("Informe a cidade com pelo menos 2 caracteres.")

    if email and not erros:
        conn = conectar()
        cursor = conn.cursor()
        if cliente_id:
            cursor.execute(
                "SELECT id FROM cliente WHERE email = ? AND id != ?",
                (email, cliente_id),
            )
        else:
            cursor.execute("SELECT id FROM cliente WHERE email = ?", (email,))
        if cursor.fetchone():
            erros.append("Este email ja esta cadastrado para outro cliente.")
        conn.close()

    dados = {
        "nome": nome,
        "email": email,
        "telefone": telefone,
        "cidade": cidade,
    }
    return len(erros) == 0, erros, dados


def buscar_clientes(termo_busca=""):
    conn = conectar()
    cursor = conn.cursor()
    termo = (termo_busca or "").strip()

    if termo:
        like = f"%{termo}%"
        cursor.execute(
            """
            SELECT * FROM cliente
            WHERE nome LIKE ? OR email LIKE ? OR telefone LIKE ? OR cidade LIKE ?
            ORDER BY nome COLLATE NOCASE
            """,
            (like, like, like, like),
        )
    else:
        cursor.execute("SELECT * FROM cliente ORDER BY nome COLLATE NOCASE")

    registros = cursor.fetchall()
    conn.close()
    return [dict(r) for r in registros]


def obter_cliente_por_id(cliente_id):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM cliente WHERE id = ?", (cliente_id,))
    registro = cursor.fetchone()
    conn.close()
    return registro


def garantir_tabela_vendas():
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS vendas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_id INTEGER NOT NULL,
            produto_id INTEGER NOT NULL,
            quantidade INTEGER NOT NULL,
            valor_total REAL NOT NULL,
            data_venda TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (cliente_id) REFERENCES cliente(id),
            FOREIGN KEY (produto_id) REFERENCES produto(id)
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_vendas_data ON vendas(data_venda)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_vendas_cliente ON vendas(cliente_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_vendas_produto ON vendas(produto_id)")
    conn.commit()
    conn.close()


def listar_clientes_para_venda():
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("SELECT id, nome, email FROM cliente ORDER BY nome COLLATE NOCASE")
    registros = cursor.fetchall()
    conn.close()
    return [dict(r) for r in registros]


def listar_produtos_para_venda():
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, nome, aroma, preco, estoque
        FROM produto
        ORDER BY nome COLLATE NOCASE
        """
    )
    registros = cursor.fetchall()
    conn.close()
    resultado = []
    for r in registros:
        item = dict(r)
        item["preco_formatado"] = formatar_preco(r["preco"])
        _, rotulo, classe = status_estoque(r["estoque"])
        item["status_rotulo"] = rotulo
        item["status_classe"] = classe
        resultado.append(item)
    return resultado


def formatar_data_venda(valor):
    if not valor:
        return "-"
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(valor, fmt).strftime("%d/%m/%Y %H:%M")
        except ValueError:
            continue
    return str(valor)


def listar_historico_vendas():
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT
            v.id,
            v.cliente_id,
            v.produto_id,
            v.quantidade,
            v.valor_total,
            v.data_venda,
            c.nome AS cliente_nome,
            p.nome AS produto_nome,
            p.aroma AS produto_aroma
        FROM vendas v
        INNER JOIN cliente c ON c.id = v.cliente_id
        INNER JOIN produto p ON p.id = v.produto_id
        ORDER BY v.data_venda DESC, v.id DESC
        """
    )
    registros = cursor.fetchall()
    conn.close()
    historico = []
    for r in registros:
        historico.append(
            {
                "id": r["id"],
                "cliente_nome": r["cliente_nome"],
                "produto_nome": r["produto_nome"],
                "produto_aroma": r["produto_aroma"],
                "quantidade": r["quantidade"],
                "valor_total": r["valor_total"],
                "valor_total_formatado": formatar_preco(r["valor_total"]),
                "data_venda": r["data_venda"],
                "data_formatada": formatar_data_venda(r["data_venda"]),
            }
        )
    return historico


def validar_venda_form(cliente_id, produto_id, quantidade_txt):
    erros = []
    cliente_num = None
    produto_num = None
    quantidade_num = None

    try:
        cliente_num = int(cliente_id)
    except (TypeError, ValueError):
        erros.append("Selecione um cliente valido.")

    try:
        produto_num = int(produto_id)
    except (TypeError, ValueError):
        erros.append("Selecione um produto valido.")

    quantidade_txt = (quantidade_txt or "").strip()
    if not quantidade_txt:
        erros.append("Informe a quantidade da venda.")
    elif not re.fullmatch(r"\d+", quantidade_txt):
        erros.append("Quantidade invalida. Use apenas numeros inteiros.")
    else:
        quantidade_num = int(quantidade_txt)
        if quantidade_num <= 0:
            erros.append("A quantidade deve ser maior que zero.")

    if erros:
        return False, erros, {}

    cliente = obter_cliente_por_id(cliente_num)
    if not cliente:
        erros.append("Cliente nao encontrado.")

    produto = obter_produto_por_id(produto_num)
    if not produto:
        erros.append("Produto nao encontrado.")
    elif quantidade_num is not None and int(produto["estoque"]) < quantidade_num:
        erros.append(
            f"Estoque insuficiente. Disponivel: {produto['estoque']} unidade(s)."
        )

    dados = {
        "cliente_id": cliente_num,
        "produto_id": produto_num,
        "quantidade": quantidade_num,
        "valor_total": float(produto["preco"]) * quantidade_num if produto else None,
    }
    return len(erros) == 0, erros, dados


def registrar_venda(dados):
    conn = conectar()
    cursor = conn.cursor()
    try:
        cursor.execute("BEGIN")
        cursor.execute(
            "SELECT id, nome, preco, estoque FROM produto WHERE id = ?",
            (dados["produto_id"],),
        )
        produto = cursor.fetchone()
        if not produto:
            conn.rollback()
            return False, ["Produto nao encontrado."]

        if int(produto["estoque"]) < dados["quantidade"]:
            conn.rollback()
            return False, [
                f"Estoque insuficiente para \"{produto['nome']}\". "
                f"Disponivel: {produto['estoque']}."
            ]

        valor_total = float(produto["preco"]) * dados["quantidade"]
        data_venda = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        cursor.execute(
            """
            INSERT INTO vendas (cliente_id, produto_id, quantidade, valor_total, data_venda)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                dados["cliente_id"],
                dados["produto_id"],
                dados["quantidade"],
                valor_total,
                data_venda,
            ),
        )
        cursor.execute(
            """
            UPDATE produto
            SET estoque = estoque - ?
            WHERE id = ? AND estoque >= ?
            """,
            (dados["quantidade"], dados["produto_id"], dados["quantidade"]),
        )
        if cursor.rowcount != 1:
            conn.rollback()
            return False, ["Nao foi possivel atualizar o estoque. Tente novamente."]

        conn.commit()
        return True, []
    except sqlite3.Error:
        conn.rollback()
        return False, ["Erro ao registrar a venda. Tente novamente."]
    finally:
        conn.close()


def obter_dados_dashboard():
    conn = conectar()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) AS total FROM produto")
    total_produtos = cursor.fetchone()["total"]

    cursor.execute("SELECT COUNT(*) AS total FROM cliente")
    total_clientes = cursor.fetchone()["total"]

    cursor.execute("SELECT COUNT(*) AS total FROM vendas")
    total_vendas = cursor.fetchone()["total"]

    cursor.execute("SELECT COALESCE(SUM(valor_total), 0) AS total FROM vendas")
    faturamento_total = float(cursor.fetchone()["total"])

    cursor.execute(
        """
        SELECT p.nome, SUM(v.quantidade) AS quantidade_vendida
        FROM vendas v
        INNER JOIN produto p ON p.id = v.produto_id
        GROUP BY v.produto_id
        ORDER BY quantidade_vendida DESC
        LIMIT 1
        """
    )
    mais_vendido = cursor.fetchone()
    produto_mais_vendido = (
        {
            "nome": mais_vendido["nome"],
            "quantidade": mais_vendido["quantidade_vendida"],
        }
        if mais_vendido
        else None
    )

    cursor.execute(
        """
        SELECT id, nome, aroma, estoque
        FROM produto
        WHERE estoque <= ?
        ORDER BY estoque ASC, nome COLLATE NOCASE
        """,
        (ESTOQUE_BAIXO_LIMITE,),
    )
    alertas_estoque = []
    for row in cursor.fetchall():
        _, rotulo, classe = status_estoque(row["estoque"])
        alertas_estoque.append(
            {
                "id": row["id"],
                "nome": row["nome"],
                "aroma": row["aroma"],
                "estoque": row["estoque"],
                "status_rotulo": rotulo,
                "status_classe": classe,
            }
        )

    cursor.execute(
        """
        SELECT date(data_venda) AS dia, SUM(valor_total) AS total
        FROM vendas
        GROUP BY date(data_venda)
        ORDER BY dia DESC
        LIMIT 7
        """
    )
    vendas_por_dia_rows = list(reversed(cursor.fetchall()))
    vendas_por_dia = {
        "labels": [r["dia"] for r in vendas_por_dia_rows],
        "valores": [float(r["total"]) for r in vendas_por_dia_rows],
    }

    cursor.execute(
        """
        SELECT p.nome, SUM(v.quantidade) AS quantidade
        FROM vendas v
        INNER JOIN produto p ON p.id = v.produto_id
        GROUP BY v.produto_id
        ORDER BY quantidade DESC
        LIMIT 5
        """
    )
    top_rows = cursor.fetchall()
    top_produtos = {
        "labels": [r["nome"] for r in top_rows],
        "quantidades": [int(r["quantidade"]) for r in top_rows],
    }

    cursor.execute(
        """
        SELECT COUNT(*) AS qtd, COALESCE(SUM(valor_total), 0) AS total
        FROM vendas
        WHERE date(data_venda) = date('now', 'localtime')
        """
    )
    vendas_hoje = cursor.fetchone()

    cursor.execute("SELECT COALESCE(AVG(valor_total), 0) AS media FROM vendas")
    ticket_medio = float(cursor.fetchone()["media"])

    conn.close()

    vendas_recentes = listar_historico_vendas()[:8]

    return {
        "total_produtos": total_produtos,
        "total_clientes": total_clientes,
        "total_vendas": total_vendas,
        "faturamento_total": faturamento_total,
        "faturamento_formatado": formatar_preco(faturamento_total),
        "produto_mais_vendido": produto_mais_vendido,
        "alertas_estoque": alertas_estoque,
        "vendas_recentes": vendas_recentes,
        "vendas_por_dia": vendas_por_dia,
        "top_produtos": top_produtos,
        "resumo_vendas": {
            "hoje_quantidade": vendas_hoje["qtd"],
            "hoje_total": float(vendas_hoje["total"]),
            "hoje_total_formatado": formatar_preco(vendas_hoje["total"]),
            "ticket_medio": ticket_medio,
            "ticket_medio_formatado": formatar_preco(ticket_medio),
        },
    }


# página inicial
@app.route('/')
@login_required
def home():
    dados = obter_dados_dashboard()
    return render_template('index.html', **dados)


@app.route('/dashboard')
@login_required
def dashboard():
    dados = obter_dados_dashboard()
    return render_template("dashboard.html", **dados)


# listar produtos
@app.route('/produtos')
@login_required
def produtos():
    termo_busca = request.args.get("q", "")
    lista = buscar_produtos(termo_busca)
    return render_template(
        "produtos.html",
        produtos=lista,
        termo_busca=termo_busca,
    )


# adicionar produto (form + insert)
@app.route('/adicionar', methods=['POST'])
@login_required
def adicionar():
    nome = request.form.get("nome", "")
    aroma = request.form.get("aroma", "")
    preco = request.form.get("preco", "")
    estoque = request.form.get("estoque", "")

    valido, erros, dados = validar_produto_form(nome, aroma, preco, estoque)
    if not valido:
        for erro in erros:
            flash(erro, "warning")
        return redirect(url_for("produtos"))

    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO produto (nome, aroma, preco, estoque)
        VALUES (?, ?, ?, ?)
        """,
        (dados["nome"], dados["aroma"], dados["preco"], dados["estoque"]),
    )
    conn.commit()
    conn.close()

    flash("Produto adicionado com sucesso.", "success")
    return redirect(url_for("produtos"))


@app.route('/editar/<int:id>', methods=['GET', 'POST'])
@login_required
def editar(id):
    produto = obter_produto_por_id(id)
    if not produto:
        flash("Produto nao encontrado.", "warning")
        return redirect(url_for("produtos"))

    if request.method == 'POST':
        nome = request.form.get("nome", "")
        aroma = request.form.get("aroma", "")
        preco = request.form.get("preco", "")
        estoque = request.form.get("estoque", "")

        valido, erros, dados = validar_produto_form(nome, aroma, preco, estoque)
        if not valido:
            for erro in erros:
                flash(erro, "warning")
            return render_template("produto_editar.html", produto=produto)

        conn = conectar()
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE produto
            SET nome = ?, aroma = ?, preco = ?, estoque = ?
            WHERE id = ?
            """,
            (dados["nome"], dados["aroma"], dados["preco"], dados["estoque"], id),
        )
        conn.commit()
        conn.close()

        flash("Produto atualizado com sucesso.", "success")
        return redirect(url_for("produtos"))

    return render_template("produto_editar.html", produto=produto)


# deletar produto
@app.route('/deletar/<int:id>')
@login_required
def deletar(id):
    produto = obter_produto_por_id(id)
    if not produto:
        flash("Produto nao encontrado.", "warning")
        return redirect(url_for("produtos"))

    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM produto WHERE id = ?", (id,))
    conn.commit()
    conn.close()

    flash(f"Produto \"{produto['nome']}\" excluido com sucesso.", "info")
    return redirect(url_for("produtos"))


@app.route('/clientes')
@login_required
def clientes():
    termo_busca = request.args.get("q", "")
    lista = buscar_clientes(termo_busca)
    return render_template(
        "clientes.html",
        clientes=lista,
        termo_busca=termo_busca,
    )


@app.route('/clientes/adicionar', methods=['POST'])
@login_required
def clientes_adicionar():
    nome = request.form.get("nome", "")
    email = request.form.get("email", "")
    telefone = request.form.get("telefone", "")
    cidade = request.form.get("cidade", "")

    valido, erros, dados = validar_cliente_form(nome, email, telefone, cidade)
    if not valido:
        for erro in erros:
            flash(erro, "warning")
        return redirect(url_for("clientes", q=request.form.get("q", "")))

    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO cliente (nome, email, telefone, cidade)
        VALUES (?, ?, ?, ?)
        """,
        (dados["nome"], dados["email"], dados["telefone"], dados["cidade"]),
    )
    conn.commit()
    conn.close()

    flash("Cliente cadastrado com sucesso.", "success")
    return redirect(url_for("clientes"))


@app.route('/clientes/editar/<int:id>', methods=['GET', 'POST'])
@login_required
def clientes_editar(id):
    cliente = obter_cliente_por_id(id)
    if not cliente:
        flash("Cliente nao encontrado.", "warning")
        return redirect(url_for("clientes"))

    if request.method == 'POST':
        nome = request.form.get("nome", "")
        email = request.form.get("email", "")
        telefone = request.form.get("telefone", "")
        cidade = request.form.get("cidade", "")

        valido, erros, dados = validar_cliente_form(nome, email, telefone, cidade, cliente_id=id)
        if not valido:
            for erro in erros:
                flash(erro, "warning")
            return render_template("cliente_editar.html", cliente=cliente)

        conn = conectar()
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE cliente
            SET nome = ?, email = ?, telefone = ?, cidade = ?
            WHERE id = ?
            """,
            (dados["nome"], dados["email"], dados["telefone"], dados["cidade"], id),
        )
        conn.commit()
        conn.close()

        flash("Cliente atualizado com sucesso.", "success")
        return redirect(url_for("clientes"))

    return render_template("cliente_editar.html", cliente=cliente)


@app.route('/clientes/deletar/<int:id>')
@login_required
def clientes_deletar(id):
    cliente = obter_cliente_por_id(id)
    if not cliente:
        flash("Cliente nao encontrado.", "warning")
        return redirect(url_for("clientes"))

    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM cliente WHERE id = ?", (id,))
    conn.commit()
    conn.close()

    flash(f"Cliente \"{cliente['nome']}\" excluido com sucesso.", "info")
    return redirect(url_for("clientes"))


@app.route('/vendas')
@login_required
def vendas():
    return render_template(
        "vendas.html",
        clientes=listar_clientes_para_venda(),
        produtos=listar_produtos_para_venda(),
        historico=listar_historico_vendas(),
    )


@app.route('/vendas/registrar', methods=['POST'])
@login_required
def vendas_registrar():
    cliente_id = request.form.get("cliente_id", "")
    produto_id = request.form.get("produto_id", "")
    quantidade = request.form.get("quantidade", "")

    valido, erros, dados = validar_venda_form(cliente_id, produto_id, quantidade)
    if not valido:
        for erro in erros:
            flash(erro, "warning")
        return redirect(url_for("vendas"))

    sucesso, erros_registro = registrar_venda(dados)
    if not sucesso:
        for erro in erros_registro:
            flash(erro, "warning")
        return redirect(url_for("vendas"))

    flash(
        f"Venda registrada com sucesso. Total: {formatar_preco(dados['valor_total'])}.",
        "success",
    )
    return redirect(url_for("vendas"))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('home'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        senha = request.form.get('senha', '')

        conn = conectar()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM usuario WHERE email = ? OR usuario = ?", (email, email))
        usuario = cursor.fetchone()
        conn.close()

        if usuario and check_password_hash(usuario["senha_hash"], senha):
            login_user(Usuario(usuario["id"], usuario["nome"], usuario["email"]))
            flash("Login realizado com sucesso.", "success")
            proxima_url = request.args.get("next")
            return redirect(proxima_url or url_for('home'))

        flash("Email ou senha invalidos.", "danger")

    return render_template('login.html')


@app.route('/cadastro', methods=['GET', 'POST'])
def cadastro():
    if current_user.is_authenticated:
        return redirect(url_for('home'))

    if request.method == 'POST':
        nome = request.form.get('nome', '').strip()
        email = request.form.get('email', '').strip().lower()
        senha = request.form.get('senha', '')

        if not nome or not email or not senha:
            flash("Preencha todos os campos.", "warning")
            return render_template('cadastro.html')

        conn = conectar()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM usuario WHERE email = ?", (email,))
        existe = cursor.fetchone()

        if existe:
            conn.close()
            flash("Este email ja esta cadastrado.", "warning")
            return render_template('cadastro.html')

        senha_hash = generate_password_hash(senha)
        cursor.execute(
            "INSERT INTO usuario (nome, email, senha_hash) VALUES (?, ?, ?)",
            (nome, email, senha_hash),
        )
        conn.commit()
        conn.close()

        flash("Cadastro realizado. Agora faça login.", "success")
        return redirect('/login')

    return render_template('cadastro.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash("Sessão encerrada com sucesso.", "info")
    return redirect('/login')


garantir_tabela_usuarios()
garantir_tabela_clientes()
garantir_tabela_vendas()


if __name__ == '__main__':
    app.run(debug=True)

@app.route("/")
def home():
    return render_template("index.html")
