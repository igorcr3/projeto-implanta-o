import hashlib
import io
import json
import logging
import os
import shutil
import sqlite3
from datetime import datetime, date, timedelta
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import plotly.express as px

# Importações opcionais para melhorias visuais avançadas (Ant Design Components)
try:
    import streamlit_antd_components as sac
    HAS_SAC = True
except ImportError:
    HAS_SAC = False

# Importação opcional para geração nativa de PDF com cabeçalho e rodapé
try:
    from reportlab.lib.pagesizes import letter, landscape
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    HAS_REPORTLAB = True
except ImportError:
    HAS_REPORTLAB = False

# ==================== CONFIGURAÇÃO DE LOGS & AUDITORIA ====================
DB_NAME = 'atende_projetos.db'

logging.basicConfig(
    filename='sistema.log',
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    encoding='utf-8',
)


def registrar_log(mensagem, usuario=None, acao=None, detalhes=None):
    logging.info(f"[{usuario or 'SISTEMA'}] - {mensagem}")
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        usr = usuario or (st.session_state.get('usuario_logado') if 'st' in globals() and hasattr(st, 'session_state') else 'SISTEMA')
        cursor.execute("""
            INSERT INTO logs_auditoria (usuario, acao, detalhes, data_hora)
            VALUES (?, ?, ?, ?)
        """, (usr, acao or 'AÇÃO', detalhes or mensagem, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"Erro ao salvar audit log: {e}")


def hash_senha(senha):
    return hashlib.sha256(senha.encode()).hexdigest()


# ==================== BANCO DE DADOS & MIGRAÇÕES ====================
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            senha TEXT NOT NULL,
            perfil TEXT DEFAULT NULL,
            analista_id INTEGER DEFAULT NULL,
            ultimo_acesso TEXT DEFAULT NULL,
            tempo_online_minutos INTEGER DEFAULT 0,
            FOREIGN KEY (analista_id) REFERENCES analistas (id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS permissoes_usuarios (
            username TEXT PRIMARY KEY,
            gerenciar_modulos INTEGER DEFAULT 0,
            gerenciar_analistas INTEGER DEFAULT 0,
            cadastrar_projetos INTEGER DEFAULT 1,
            backup_auditoria INTEGER DEFAULT 0,
            acesso_db INTEGER DEFAULT 0,
            acesso_dashboard INTEGER DEFAULT 1,
            acesso_relatorios INTEGER DEFAULT 1,
            FOREIGN KEY (username) REFERENCES usuarios (username) ON DELETE CASCADE
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS modulos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT UNIQUE NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS analistas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT UNIQUE NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS projetos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            num_projeto TEXT UNIQUE NOT NULL,
            pipefy_link TEXT,
            emails_lista TEXT,
            modulo_id INTEGER,
            analista_id INTEGER,
            gestor TEXT,
            tel_gestor TEXT,
            resp TEXT,
            tel_resp TEXT,
            situacao TEXT NOT NULL,
            motivo_pendencia TEXT,
            ba TEXT,
            data_prevista TEXT,
            FOREIGN KEY (modulo_id) REFERENCES modulos (id),
            FOREIGN KEY (analista_id) REFERENCES analistas (id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS checklists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            projeto_id INTEGER,
            item TEXT NOT NULL,
            concluido INTEGER DEFAULT 0,
            ordem INTEGER DEFAULT 0,
            FOREIGN KEY (projeto_id) REFERENCES projetos (id) ON DELETE CASCADE
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS anexos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            projeto_id INTEGER,
            checklist_id INTEGER,
            nome_arquivo TEXT NOT NULL,
            dados_arquivo BLOB,
            tipo_arquivo TEXT,
            data_upload TEXT,
            FOREIGN KEY (projeto_id) REFERENCES projetos (id) ON DELETE CASCADE,
            FOREIGN KEY (checklist_id) REFERENCES checklists (id) ON DELETE CASCADE
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tempo_projetos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            projeto_id INTEGER,
            usuario TEXT,
            data_registro TEXT,
            minutos_gastos INTEGER DEFAULT 0,
            FOREIGN KEY (projeto_id) REFERENCES projetos (id) ON DELETE CASCADE
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cronometro_ativo_db (
            username TEXT PRIMARY KEY,
            projeto_id INTEGER,
            inicio TEXT,
            segundos_acumulados INTEGER DEFAULT 0,
            status TEXT DEFAULT 'rodando'
        )
    """)

    try:
        cursor.execute("SELECT segundos_acumulados FROM cronometro_ativo_db LIMIT 1")
    except sqlite3.OperationalError:
        cursor.execute("ALTER TABLE cronometro_ativo_db ADD COLUMN segundos_acumulados INTEGER DEFAULT 0")

    try:
        cursor.execute("SELECT status FROM cronometro_ativo_db LIMIT 1")
    except sqlite3.OperationalError:
        cursor.execute("ALTER TABLE cronometro_ativo_db ADD COLUMN status TEXT DEFAULT 'rodando'")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS comentarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            projeto_id INTEGER,
            autor TEXT,
            texto TEXT,
            data TEXT,
            FOREIGN KEY (projeto_id) REFERENCES projetos (id) ON DELETE CASCADE
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS notificacoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            projeto_id INTEGER,
            destinatario TEXT,
            remetente TEXT,
            mensagem TEXT,
            data TEXT,
            lida INTEGER DEFAULT 0,
            FOREIGN KEY (projeto_id) REFERENCES projetos (id) ON DELETE CASCADE
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS agenda (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titulo TEXT NOT NULL,
            url TEXT,
            criador TEXT NOT NULL,
            compartilhado_com TEXT,
            data_inicio TEXT NOT NULL,
            data_fim TEXT NOT NULL,
            lembrete_minutos INTEGER DEFAULT 10,
            projeto_id INTEGER,
            notificado_popup INTEGER DEFAULT 0,
            FOREIGN KEY (projeto_id) REFERENCES projetos (id) ON DELETE SET NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS logs_auditoria (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario TEXT NOT NULL,
            acao TEXT NOT NULL,
            detalhes TEXT,
            data_hora TEXT NOT NULL
        )
    """)

    cursor.execute('SELECT COUNT(*) FROM usuarios WHERE perfil = "Administrador"')
    if cursor.fetchone()[0] == 0:
        cursor.execute(
            'INSERT OR IGNORE INTO usuarios (username, senha, perfil) VALUES (?, ?, ?)',
            ('admin', hash_senha('admin123'), 'Administrador'),
        )
        cursor.execute(
            'INSERT OR IGNORE INTO permissoes_usuarios VALUES ("admin", 1, 1, 1, 1, 1, 1, 1)'
        )

    conn.commit()
    conn.close()


init_db()

# ==================== CONFIGURAÇÃO STREAMLIT & DESIGN SYSTEM ====================
st.set_page_config(
    page_title='Gestão de Implantações', 
    page_icon='⚡', 
    layout='wide'
)

st.markdown("""
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    
    <style>
    * {
        font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif;
    }
    header[data-testid="stHeader"] {
        background-color: transparent !important;
        border: none !important;
        z-index: 999999;
    }
    header[data-testid="stHeader"] svg {
        fill: #ffffff !important;
        color: #ffffff !important;
    }
    .block-container {
        padding-top: 0.8rem !important;
        padding-bottom: 4rem !important;
        max-width: 100% !important;
    }
    .main { 
        background: #0f172a; 
        color: #f8fafc;
    }
    .stButton>button {
        border-radius: 8px !important;
        font-weight: 600 !important;
        transition: all 0.25s ease-in-out !important;
        border: 1px solid #334155 !important;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.2) !important;
    }
    .stButton>button:hover {
        transform: translateY(-1px) !important;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3) !important;
        border-color: #475569 !important;
    }
    div[data-baseweb="input"], div[data-baseweb="select"] {
        border-radius: 8px !important;
    }
    .stCheckbox label span {
        white-space: pre-wrap !important;
        word-break: break-word !important;
        overflow-wrap: break-word !important;
        line-height: 1.4 !important;
    }
    .app-header {
        position: relative;
        left: 50%;
        right: 50%;
        margin-left: -50vw;
        margin-right: -50vw;
        width: 100vw;
        background: linear-gradient(135deg, #090d16 0%, #1e293b 50%, #0f172a 100%);
        color: #ffffff;
        padding: 0.8rem 2rem;
        margin-top: -3rem;
        margin-bottom: 1.5rem;
        box-shadow: 0 8px 20px -8px rgba(15, 23, 42, 0.6);
        border-bottom: 2px solid #3b82f6;
    }
    .header-content {
        max-width: 1600px;
        margin: 0 auto;
        display: flex;
        justify-content: space-between;
        align-items: center;
        flex-wrap: wrap;
        gap: 15px;
    }
    .header-title {
        display: flex;
        align-items: center;
        gap: 12px;
    }
    .header-title-icon {
        width: 38px;
        height: 38px;
        background: linear-gradient(135deg, #3b82f6, #2563eb);
        border-radius: 10px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 1.1rem;
        color: #ffffff;
        box-shadow: 0 4px 12px rgba(59, 130, 246, 0.4);
    }
    .header-title h1 {
        margin: 0;
        font-size: 1.35rem;
        font-weight: 800;
        color: #ffffff;
        letter-spacing: -0.5px;
    }
    .header-title p {
        margin: 0;
        color: #94a3b8;
        font-size: 0.78rem;
    }
    .header-user-badge {
        background: rgba(255, 255, 255, 0.05);
        backdrop-filter: blur(10px);
        padding: 6px 14px;
        border-radius: 10px;
        border: 1px solid rgba(255, 255, 255, 0.12);
        display: flex;
        align-items: center;
        gap: 12px;
    }
    .user-info span {
        display: block;
        font-size: 0.65rem;
        color: #94a3b8;
        text-transform: uppercase;
        letter-spacing: 0.8px;
        font-weight: 700;
    }
    .user-info strong {
        font-size: 0.88rem;
        color: #38bdf8;
    }
    .badge-perfil {
        background: linear-gradient(135deg, #3b82f6, #1d4ed8);
        color: #ffffff;
        font-size: 0.7rem;
        padding: 4px 10px;
        border-radius: 20px;
        font-weight: 700;
        letter-spacing: 0.3px;
        box-shadow: 0 2px 6px rgba(59, 130, 246, 0.3);
    }
    .app-footer {
        position: relative;
        left: 50%;
        right: 50%;
        margin-left: -50vw;
        margin-right: -50vw;
        width: 100vw;
        background-color: #090d16;
        color: #94a3b8;
        padding: 0.8rem 2rem;
        margin-top: 3rem;
        border-top: 1px solid #1e293b;
        text-align: center;
        font-size: 0.8rem;
        clear: both;
    }
    .footer-inner {
        max-width: 1600px;
        margin: 0 auto;
        display: flex;
        justify-content: space-between;
        align-items: center;
        flex-wrap: wrap;
        gap: 12px;
    }
    .footer-links a {
        color: #38bdf8;
        text-decoration: none;
        margin: 0 8px;
        transition: color 0.2s;
    }
    .footer-links a:hover {
        color: #60a5fa;
    }
    </style>
""", unsafe_allow_html=True)

PALETA_CORES_STATUS = {
    'Em Aberto': '#0284c7',
    'Em Andamento': '#eab308',
    'Pendente': '#ef4444',
    'Finalizado': '#22c55e',
}

# ==================== CONTROLE DE SESSÃO ====================
query_params = st.query_params

if 'usuario_logado' not in st.session_state:
    if 'user' in query_params and 'perfil' in query_params:
        st.session_state.usuario_logado = query_params['user']
        st.session_state.perfil_logado = query_params['perfil']
    else:
        st.session_state.usuario_logado = None
        st.session_state.perfil_logado = None

if 'modal_projeto_id' not in st.session_state:
    st.session_state.modal_projeto_id = None

if 'modal_historico_id' not in st.session_state:
    st.session_state.modal_historico_id = None

if 'show_historico_modal' not in st.session_state:
    st.session_state.show_historico_modal = False

if 'active_tab_modal' not in st.session_state:
    st.session_state.active_tab_modal = 0

if 'popup_mensagens' not in st.session_state:
    st.session_state.popup_mensagens = []

if 'notifs_processadas' not in st.session_state:
    st.session_state.notifs_processadas = set()


def atualizar_query_params():
    if st.session_state.usuario_logado:
        st.query_params['user'] = st.session_state.usuario_logado
        st.query_params['perfil'] = st.session_state.perfil_logado
    else:
        st.query_params.clear()

def formatar_data_br(dt_str):
    if not dt_str:
        return ""
    try:
        if len(dt_str) > 10:
            dt_obj = datetime.strptime(dt_str, '%Y-%m-%d %H:%M')
            return dt_obj.strftime('%d-%m-%Y %H:%M')
        else:
            dt_obj = datetime.strptime(dt_str, '%Y-%m-%d')
            return dt_obj.strftime('%d-%m-%Y')
    except Exception:
        return dt_str

def calcular_tempo_restante(dt_ini_str, dt_fim_str=None):
    try:
        dt_ini = datetime.strptime(dt_ini_str, '%Y-%m-%d %H:%M')
        dt_fim = datetime.strptime(dt_fim_str, '%Y-%m-%d %H:%M') if dt_fim_str else None
        agora = datetime.now()
        
        if dt_fim and agora > dt_fim:
            return "🟢 Finalizado"
        
        diff = dt_ini - agora
        total_sec = diff.total_seconds()
        if total_sec < 0:
            return "🟢 Em andamento / Acontecendo"
        
        dias = int(total_sec // 86400)
        horas = int((total_sec % 86400) // 3600)
        mins = int((total_sec % 3600) // 60)
        
        partes = []
        if dias > 0:
            partes.append(f"{dias}d")
        if horas > 0:
            partes.append(f"{horas}h")
        if mins > 0 or not partes:
            partes.append(f"{mins}min")
        return f"⏳ Faltam {' '.join(partes)}"
    except Exception:
        return ""

# ==================== TELA DE LOGIN ESTILIZADA ====================
def tela_login_cadastro():
    st.markdown("""
        <div style="text-align: center; margin-top: 2rem; margin-bottom: 2rem;">
            <div style="display: inline-flex; width: 64px; height: 64px; background: linear-gradient(135deg, #3b82f6, #1d4ed8); border-radius: 16px; align-items: center; justify-content: center; font-size: 2rem; color: white; box-shadow: 0 10px 25px -5px rgba(59, 130, 246, 0.5); margin-bottom: 12px;">
                <i class="fa-solid fa-bolt"></i>
            </div>
            <h2 style="font-weight: 800; color: #f8fafc; margin: 0; font-size: 2rem; letter-spacing: -0.5px;">Sistema de Implantações</h2>
            <p style="color: #94a3b8; margin-top: 6px; font-size: 1rem;">Gestão de projetos, agendamentos e controle de recursos</p>
        </div>
    """, unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 1.8, 1])

    with col2:
        aba_l, aba_c = st.tabs(['🔑 Entrar', '📝 Criar Conta'])

        with aba_l:
            with st.form('form_login'):
                st.markdown('##### <i class="fa-solid fa-lock" style="color: #3b82f6;"></i> Acessar a Plataforma', unsafe_allow_html=True)
                user = st.text_input('Usuário', placeholder='Digite seu usuário...', key='login_user_inp')
                senha = st.text_input('Senha', type='password', placeholder='Digite sua senha...', key='login_senha_inp')
                submitted = st.form_submit_button('Entrar no Sistema', use_container_width=True)

                if submitted:
                    conn = sqlite3.connect(DB_NAME)
                    cursor = conn.cursor()
                    cursor.execute('SELECT senha, perfil FROM usuarios WHERE username = ?', (user,))
                    res = cursor.fetchone()
                    conn.close()

                    if res and res[0] == hash_senha(senha):
                        if res[1] is None or res[1].strip() == '':
                            st.warning('Sua conta aguarda aprovação de um Administrador para receber um perfil de acesso.')
                        else:
                            st.session_state.usuario_logado = user
                            st.session_state.perfil_logado = res[1]
                            atualizar_query_params()
                            registrar_log('Usuário efetuou login no sistema.', usuario=user, acao='LOGIN')
                            st.success('Login realizado com sucesso!')
                            st.rerun()
                    else:
                        st.error('Usuário ou senha incorretos.')

        with aba_c:
            with st.form('form_cadastro_externo'):
                st.markdown('##### <i class="fa-solid fa-id-card" style="color: #10b981;"></i> Nova Conta de Acesso', unsafe_allow_html=True)
                novo_u = st.text_input('Escolha um Usuário', placeholder='ex: joao.silva', key='cad_user_inp')
                nova_s = st.text_input('Escolha uma Senha', type='password', placeholder='Mínimo 6 caracteres...', key='cad_senha_inp')
                cad_submitted = st.form_submit_button('Solicitar Cadastro', use_container_width=True)

                if cad_submitted:
                    if novo_u.strip() and nova_s.strip():
                        try:
                            conn = sqlite3.connect(DB_NAME)
                            cursor = conn.cursor()
                            cursor.execute(
                                'INSERT INTO usuarios (username, senha, perfil) VALUES (?, ?, NULL)',
                                (novo_u.strip(), hash_senha(nova_s)),
                            )
                            cursor.execute(
                                'INSERT INTO permissoes_usuarios (username) VALUES (?)',
                                (novo_u.strip(),),
                            )
                            conn.commit()
                            conn.close()
                            registrar_log(f'Solicitação de cadastro do usuário {novo_u.strip()}.', usuario=novo_u.strip(), acao='CRIAR_CONTA')
                            st.success('Conta criada com sucesso! Solicite ao Administrador a liberação do perfil.')
                        except sqlite3.IntegrityError:
                            st.error('Este nome de usuário já está em uso.')
                    else:
                        st.warning('Preencha todos os campos.')

if not st.session_state.usuario_logado:
    tela_login_cadastro()
    st.stop()

# ==================== VERIFICAÇÃO AUTOMÁTICA EM SEGUNDO PLANO (POLLING) ====================
@st.fragment(run_every=30)
def background_polling_worker():
    if not st.session_state.get('usuario_logado'):
        return
    
    usr = st.session_state.usuario_logado
    agora = datetime.now()
    
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        agora_str = agora.strftime('%Y-%m-%d %H:%M:%S')
        cursor.execute("UPDATE usuarios SET ultimo_acesso = ?, tempo_online_minutos = tempo_online_minutos + 1 WHERE username = ?", (agora_str, usr))
        
        cursor.execute("""
            SELECT id, mensagem FROM notificacoes 
            WHERE destinatario = ? AND lida = 0 ORDER BY id DESC
        """, (usr,))
        notifs_db = cursor.fetchall()
        
        novas_encontradas = False
        for n_id, n_msg in notifs_db:
            if n_id not in st.session_state.notifs_processadas:
                st.session_state.notifs_processadas.add(n_id)
                pop_id = f"notif_db_{n_id}"
                if not any(p['id'] == pop_id for p in st.session_state.popup_mensagens):
                    st.session_state.popup_mensagens.append({
                        'id': pop_id,
                        'titulo': "📥 Nova Notificação Recebida",
                        'mensagem': n_msg
                    })
                    novas_encontradas = True

        cursor.execute("""
            SELECT id, titulo, data_inicio, lembrete_minutos 
            FROM agenda 
            WHERE (criador = ? OR compartilhado_com LIKE ? OR compartilhado_com LIKE ? OR compartilhado_com = ?) AND notificado_popup = 0
        """, (usr, f"%{usr}%", usr, usr))
        eventos = cursor.fetchall()
        
        for ev_id, tit, dt_ini_str, lembrete_min in eventos:
            try:
                dt_ini = datetime.strptime(dt_ini_str, '%Y-%m-%d %H:%M')
                diff_min = (dt_ini - agora).total_seconds() / 60.0
                
                if 0 <= diff_min <= lembrete_min:
                    cursor.execute("UPDATE agenda SET notificado_popup = 1 WHERE id = ?", (ev_id,))
                    conn.commit()
                    
                    msg_popup = f"Reunião '{tit}' inicia em {int(diff_min)} min (Início: {formatar_data_br(dt_ini_str)})"
                    pop_id_agenda = f"lembrete_{ev_id}"
                    if not any(p['id'] == pop_id_agenda for p in st.session_state.popup_mensagens):
                        st.session_state.popup_mensagens.append({
                            'id': pop_id_agenda,
                            'titulo': "🚨 Alerta de Reunião Próxima",
                            'mensagem': msg_popup
                        })
                        novas_encontradas = True
            except Exception:
                pass

        conn.commit()
        conn.close()
        
        if novas_encontradas:
            st.rerun()
    except Exception:
        pass

background_polling_worker()

# ==================== FUNÇÕES AUXILIARES & PERMISSÕES ====================
def get_connection():
    return sqlite3.connect(DB_NAME)

def carregar_permissoes_usuario(username):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT gerenciar_modulos, gerenciar_analistas, cadastrar_projetos, backup_auditoria, acesso_db,
               COALESCE(acesso_dashboard, 1), COALESCE(acesso_relatorios, 1)
        FROM permissoes_usuarios WHERE username = ?
    """, (username,))
    res = cursor.fetchone()
    conn.close()
    if res:
        return {
            'modulos': bool(res[0]),
            'analistas': bool(res[1]),
            'cadastrar': bool(res[2]),
            'backup': bool(res[3]),
            'acesso_db': bool(res[4]),
            'dashboard': bool(res[5]),
            'relatorios': bool(res[6]),
        }
    return {'modulos': False, 'analistas': False, 'cadastrar': True, 'backup': False, 'acesso_db': False, 'dashboard': True, 'relatorios': True}

def carregar_analista_do_usuario(username):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT a.id, a.nome FROM usuarios u
        LEFT JOIN analistas a ON u.analista_id = a.id
        WHERE u.username = ?
    """, (username,))
    res = cursor.fetchone()
    conn.close()
    return res if res and res[0] else (None, None)

def carregar_modulos():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT id, nome FROM modulos ORDER BY nome')
    res = cursor.fetchall()
    conn.close()
    return res

def carregar_analistas():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT id, nome FROM analistas ORDER BY nome')
    res = cursor.fetchall()
    conn.close()
    return res

def carregar_usuarios_sistema():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT username FROM usuarios WHERE perfil IS NOT NULL ORDER BY username')
    res = [r[0] for r in cursor.fetchall()]
    conn.close()
    return res

def carregar_projetos():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT p.id, p.num_projeto, p.pipefy_link, p.emails_lista, m.nome as modulo, a.nome as analista, 
               p.gestor, p.tel_gestor, p.resp, p.tel_resp, p.situacao, p.motivo_pendencia, 
               p.ba, p.data_prevista, p.modulo_id, p.analista_id
        FROM projetos p
        LEFT JOIN modulos m ON p.modulo_id = m.id
        LEFT JOIN analistas a ON p.analista_id = a.id
        ORDER BY p.id DESC
    """)
    res = cursor.fetchall()
    conn.close()
    return res

def carregar_checklist(projeto_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT id, item, concluido, ordem FROM checklists WHERE projeto_id = ? ORDER BY ordem ASC, id ASC', (projeto_id,))
    res = cursor.fetchall()
    conn.close()
    return res

def carregar_anexos_projeto(projeto_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT id, checklist_id, nome_arquivo, dados_arquivo, tipo_arquivo, data_upload FROM anexos WHERE projeto_id = ? ORDER BY id DESC', (projeto_id,))
    res = cursor.fetchall()
    conn.close()
    return res

def calcular_progresso_checklist(projeto_id):
    items = carregar_checklist(projeto_id)
    if not items:
        return 0
    concluidos = sum(1 for item in items if item[2] == 1)
    return int((concluidos / len(items)) * 100)

def calcular_horas_projeto(projeto_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT COALESCE(SUM(minutos_gastos), 0) FROM tempo_projetos WHERE projeto_id = ?', (projeto_id,))
    total_min = cursor.fetchone()[0]
    conn.close()
    horas = total_min // 60
    mins = total_min % 60
    if horas > 0:
        return f"{horas}h {mins}m"
    return f"{mins}m"

def carregar_comentarios(projeto_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT id, autor, texto, data FROM comentarios WHERE projeto_id = ? ORDER BY id DESC', (projeto_id,))
    res = cursor.fetchall()
    conn.close()
    return res

def carregar_reuniao_projeto(projeto_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT titulo, data_inicio, data_fim, url FROM agenda 
        WHERE projeto_id = ? ORDER BY data_inicio ASC LIMIT 1
    """, (projeto_id,))
    res = cursor.fetchone()
    conn.close()
    return res

def carregar_historico_notificacoes_projeto(projeto_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT n.id, n.remetente, n.destinatario, n.mensagem, n.data 
        FROM notificacoes n
        INNER JOIN projetos p ON n.projeto_id = p.id
        WHERE n.projeto_id = ? ORDER BY n.id DESC
    """, (projeto_id,))
    res = cursor.fetchall()
    conn.close()

    agrupadas = {}
    for notif_id, rem, dest, msg, data_n in res:
        chave = (rem, msg, data_n)
        if chave not in agrupadas:
            agrupadas[chave] = {'dests': [], 'ids': []}
        agrupadas[chave]['dests'].append(dest)
        agrupadas[chave]['ids'].append(notif_id)

    resultado_final = []
    for (rem, msg, data_n), info in agrupadas.items():
        dests_str = ', '.join([f'@{d}' for d in sorted(info['dests'])])
        resultado_final.append((rem, dests_str, msg, data_n, info['ids']))

    return resultado_final

# ==================== GERENCIAMENTO DE PDF COM CABEÇALHO E RODAPÉ ====================
def add_header_footer(canvas, doc):
    canvas.saveState()
    canvas.setFont('Helvetica-Bold', 9)
    canvas.setFillColor(colors.HexColor('#0f172a'))
    
    canvas.drawString(30, 580 if doc.pagesize[0] > 700 else 760, "SISTEMA DE IMPLANTAÇÕES — RELATÓRIO OFICIAL")
    canvas.setFont('Helvetica', 8)
    canvas.setFillColor(colors.HexColor('#64748b'))
    canvas.drawRightString(762 if doc.pagesize[0] > 700 else 582, 580 if doc.pagesize[0] > 700 else 760, f"Gerado em: {datetime.now().strftime('%d-%m-%Y %H:%M')}")
    
    canvas.setStrokeColor(colors.HexColor('#cbd5e1'))
    canvas.setLineWidth(0.5)
    canvas.line(30, 572 if doc.pagesize[0] > 700 else 752, 762 if doc.pagesize[0] > 700 else 582, 572 if doc.pagesize[0] > 700 else 752)
    
    canvas.line(30, 40, 762 if doc.pagesize[0] > 700 else 582, 40)
    canvas.drawString(30, 28, f"Usuário Responsável: @{st.session_state.usuario_logado}")
    canvas.drawRightString(762 if doc.pagesize[0] > 700 else 582, 28, f"Página {doc.page}")
    canvas.restoreState()

def gerar_pdf_relatorio(dataframe, colunas):
    if not HAS_REPORTLAB:
        return None
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(letter), rightMargin=30, leftMargin=30, topMargin=75, bottomMargin=50)
    elements = []
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(name='TitleStyle', parent=styles['Heading1'], fontSize=15, leading=18, textColor=colors.HexColor('#0f172a'))
    elements.append(Paragraph("Relatório de Implantações e Projetos", title_style))
    elements.append(Spacer(1, 10))

    cell_style = ParagraphStyle(name='CellText', parent=styles['Normal'], fontSize=8, leading=10, textColor=colors.HexColor('#1e293b'))

    data = [[Paragraph(f"<b>{col}</b>", cell_style) for col in colunas]]
    for _, row in dataframe.iterrows():
        data.append([Paragraph(str(row[col]), cell_style) for col in colunas])

    t = Table(data)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0f172a')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#f8fafc')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
    ]))
    elements.append(t)
    doc.build(elements, onFirstPage=add_header_footer, onLaterPages=add_header_footer)
    buffer.seek(0)
    return buffer.getvalue()

def gerar_pdf_checklist(p_num, chk_items):
    if not HAS_REPORTLAB:
        return None
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=30, leftMargin=30, topMargin=75, bottomMargin=50)
    elements = []
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(name='TitleStyle', parent=styles['Heading1'], fontSize=15, leading=18, textColor=colors.HexColor('#0f172a'))
    elements.append(Paragraph(f"Checklist do Projeto: {p_num}", title_style))
    elements.append(Spacer(1, 10))

    body_style = ParagraphStyle(name='ChkBody', parent=styles['Normal'], fontSize=9, leading=12, textColor=colors.HexColor('#0f172a'))

    data = [["Status", "Item do Checklist"]]
    for _, item_name, concluido, _ in chk_items:
        status_txt = "CONCLUÍDO [X]" if concluido == 1 else "PENDENTE [ ]"
        data.append([status_txt, Paragraph(item_name, body_style)])

    t = Table(data, colWidths=[120, 350])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0f172a')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#f8fafc')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    elements.append(t)
    doc.build(elements, onFirstPage=add_header_footer, onLaterPages=add_header_footer)
    buffer.seek(0)
    return buffer.getvalue()

def gerar_pdf_checklist_filtrados(lista_projetos_filtrados):
    if not HAS_REPORTLAB:
        return None
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=30, leftMargin=30, topMargin=75, bottomMargin=50)
    elements = []
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(name='TitleStyle', parent=styles['Heading1'], fontSize=15, leading=18, textColor=colors.HexColor('#0f172a'))
    body_style = ParagraphStyle(name='ChkBodyFilt', parent=styles['Normal'], fontSize=9, leading=12, textColor=colors.HexColor('#0f172a'))
    
    elements.append(Paragraph("Relatório Consolidado de Checklists por Filtro", title_style))
    elements.append(Spacer(1, 10))

    for p in lista_projetos_filtrados:
        p_id, p_num, p_mod, p_an, p_sit = p[0], p[1], p[4], p[5], p[10]
        elements.append(Paragraph(f"<b>Projeto: {p_num}</b> | Módulo: {p_mod or 'N/D'} | Analista: {p_an or 'N/D'} | Status: {p_sit}", styles['Heading2']))
        
        chk_items = carregar_checklist(p_id)
        if chk_items:
            data = [["Status", "Item do Checklist"]]
            for _, item_name, concluido, _ in chk_items:
                status_txt = "CONCLUÍDO [X]" if concluido == 1 else "PENDENTE [ ]"
                data.append([status_txt, Paragraph(item_name, body_style)])
            
            t = Table(data, colWidths=[110, 370])
            t.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#334155')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 9),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
                ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#f8fafc')),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ]))
            elements.append(t)
        else:
            elements.append(Paragraph("Nenhum item de checklist cadastrado.", styles['Normal']))
        elements.append(Spacer(1, 10))

    doc.build(elements, onFirstPage=add_header_footer, onLaterPages=add_header_footer)
    buffer.seek(0)
    return buffer.getvalue()

# ==================== MODAIS ====================
@st.dialog('🔔 Histórico de Notificações do Projeto', width='medium')
def modal_historico_notificacoes(p_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT p.num_projeto FROM notificacoes n
        INNER JOIN projetos p ON n.projeto_id = p.id
        WHERE n.projeto_id = ? LIMIT 1
    """, (p_id,))
    res = cursor.fetchone()
    conn.close()

    if not res:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT num_projeto FROM projetos WHERE id = ?', (p_id,))
        res_p = cursor.fetchone()
        conn.close()
        if not res_p:
            st.warning('Este projeto não existe mais ou foi excluído permanentemente.')
            if st.button('Fechar', key='btn_close_hist_err'):
                st.session_state.modal_historico_id = None
                st.session_state.show_historico_modal = False
                st.rerun()
            return
        p_num = res_p[0]
    else:
        p_num = res[0]

    st.markdown(f'#### Projeto: **{p_num}**')
    st.markdown('---')

    notifs = carregar_historico_notificacoes_projeto(p_id)
    if notifs:
        for rem, dests_fmt, msg, data_n, ids_list in notifs:
            col_msg, col_del = st.columns([0.88, 0.12])
            with col_msg:
                st.info(f"**De:** @{rem} ➔ **Para:** {dests_fmt} em *{data_n}*\n\n{msg}", icon='📢')
            with col_del:
                if st.session_state.perfil_logado == 'Administrador':
                    if st.button('🗑️', key=f'del_notif_grupo_{ids_list[0]}', help='Remover mensagem para todos'):
                        conn_d = get_connection()
                        cursor_d = conn_d.cursor()
                        for nid in ids_list:
                            cursor_d.execute('DELETE FROM notificacoes WHERE id = ?', (nid,))
                        conn_d.commit()
                        conn_d.close()
                        registrar_log(f"Mensagem de notificação do projeto {p_num} removida pelo administrador.", acao='EXCLUIR_NOTIFICACAO')
                        st.success('Mensagem removida!')
                        st.rerun()
    else:
        st.caption('Nenhuma notificação registrada para este projeto.')

    if st.button('Fechar Histórico', key='btn_close_hist', use_container_width=True):
        st.session_state.modal_historico_id = None
        st.session_state.show_historico_modal = False
        st.rerun()

@st.dialog('🔍 Gerenciamento Detalhado do Projeto', width='large')
def modal_gerenciar_projeto(p_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT p.id, p.num_projeto, p.pipefy_link, p.emails_lista, m.nome as modulo, a.nome as analista, 
               p.gestor, p.tel_gestor, p.resp, p.tel_resp, p.situacao, p.motivo_pendencia, 
               p.ba, p.data_prevista, p.modulo_id, p.analista_id
        FROM projetos p
        LEFT JOIN modulos m ON p.modulo_id = m.id
        LEFT JOIN analistas a ON p.analista_id = a.id
        WHERE p.id = ?
    """, (p_id,))
    p = cursor.fetchone()
    conn.close()

    if not p:
        st.error('Projeto não encontrado.')
        if st.button('Fechar', key='btn_fech_err'):
            st.session_state.modal_projeto_id = None
            st.rerun()
        return

    (p_id, p_num, p_pipefy, p_emails_str, p_modulo, p_analista, p_gestor, p_tel_g, p_resp, p_tel_r, 
     p_sit, p_motivo, p_ba, p_data_prev, p_mod_id, p_analista_id) = p

    col_titulo, col_fechar = st.columns([0.85, 0.15])
    with col_titulo:
        st.markdown(f'### Projeto: **{p_num}** | Módulo: **{p_modulo or "N/D"}** | Analista: **{p_analista or "N/D"}**')
    with col_fechar:
        if st.button('❌ Fechar', key=f'btn_fechar_modal_top_{p_id}'):
            st.session_state.modal_projeto_id = None
            st.session_state.active_tab_modal = 0
            st.rerun()

    st.markdown('---')

    @st.fragment(run_every=1)
    def render_cronometro_vivo(proj_id, proj_num):
        usr_atual = st.session_state.usuario_logado
        
        col_cr1, col_cr2, col_cr3 = st.columns([0.35, 0.4, 0.25])
        with col_cr1:
            total_h_proj = calcular_horas_projeto(proj_id)
            st.markdown(f"⏱️ **Tempo Total Registrado:** `{total_h_proj}`")
        with col_cr2:
            conn_t = get_connection()
            cursor_t = conn_t.cursor()
            cursor_t.execute("SELECT projeto_id, inicio, segundos_acumulados, status FROM cronometro_ativo_db WHERE username = ?", (usr_atual,))
            user_timer = cursor_t.fetchone()
            
            cursor_t.execute("SELECT projeto_id, status FROM cronometro_ativo_db WHERE username = ? AND projeto_id != ?", (usr_atual, proj_id))
            other_timer = cursor_t.fetchone()
            
            cursor_t.execute("SELECT username, inicio, segundos_acumulados, status FROM cronometro_ativo_db WHERE projeto_id = ?", (proj_id,))
            all_proj_timers = cursor_t.fetchall()
            conn_t.close()

            if other_timer:
                st.warning(f"⚠️ Você já possui um cronômetro ativo em outro projeto. Pause ou finalize-o primeiro.")
            else:
                if not user_timer or user_timer[0] != proj_id:
                    if st.button("▶️ Iniciar Cronômetro", key=f"start_cron_{proj_id}", use_container_width=True):
                        conn_ins = get_connection()
                        cursor_ins = conn_ins.cursor()
                        cursor_ins.execute("""
                            INSERT INTO cronometro_ativo_db (username, projeto_id, inicio, segundos_acumulados, status)
                            VALUES (?, ?, ?, 0, 'rodando')
                            ON CONFLICT(username) DO UPDATE SET projeto_id=excluded.projeto_id, inicio=excluded.inicio, segundos_acumulados=0, status='rodando'
                        """, (usr_atual, proj_id, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
                        conn_ins.commit()
                        conn_ins.close()
                        st.success("Cronômetro iniciado!")
                        st.rerun()
                else:
                    _, ini_str, seg_acum, t_status = user_timer
                    
                    sub_btn1, sub_btn2, sub_btn3 = st.columns(3)
                    with sub_btn1:
                        if t_status == 'rodando':
                            if st.button("⏸️ Pausar", key=f"pause_cron_{proj_id}", use_container_width=True):
                                dt_inicio = datetime.strptime(ini_str, '%Y-%m-%d %H:%M:%S')
                                elapsed = int((datetime.now() - dt_inicio).total_seconds())
                                novo_seg_acum = seg_acum + elapsed
                                
                                conn_p = get_connection()
                                cursor_p = conn_p.cursor()
                                cursor_p.execute("""
                                    UPDATE cronometro_ativo_db 
                                    SET segundos_acumulados = ?, status = 'pausado', inicio = NULL 
                                    WHERE username = ?
                                """, (novo_seg_acum, usr_atual))
                                conn_p.commit()
                                conn_p.close()
                                st.rerun()
                        else:
                            if st.button("▶️ Retomar", key=f"resume_cron_{proj_id}", use_container_width=True):
                                conn_r = get_connection()
                                cursor_r = conn_r.cursor()
                                cursor_r.execute("""
                                    UPDATE cronometro_ativo_db 
                                    SET inicio = ?, status = 'rodando' 
                                    WHERE username = ?
                                """, (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), usr_atual))
                                conn_r.commit()
                                conn_r.close()
                                st.rerun()
                    with sub_btn2:
                        if st.button("⏹️ Finalizar", key=f"stop_cron_{proj_id}", use_container_width=True):
                            total_secs = seg_acum
                            if t_status == 'rodando' and ini_str:
                                dt_inicio = datetime.strptime(ini_str, '%Y-%m-%d %H:%M:%S')
                                total_secs += int((datetime.now() - dt_inicio).total_seconds())
                            
                            minutos_totais = max(1, total_secs // 60)
                            
                            conn_f = get_connection()
                            cursor_f = conn_f.cursor()
                            cursor_f.execute("""
                                INSERT INTO tempo_projetos (projeto_id, usuario, data_registro, minutos_gastos)
                                VALUES (?, ?, ?, ?)
                            """, (proj_id, usr_atual, datetime.now().strftime('%Y-%m-%d'), minutos_totais))
                            cursor_f.execute("DELETE FROM cronometro_ativo_db WHERE username = ?", (usr_atual,))
                            conn_f.commit()
                            conn_f.close()
                            
                            registrar_log(f"Cronômetro finalizado no projeto {proj_num} por @{usr_atual}: {minutos_totais} minutos.", acao='CRONOMETRO')
                            st.success(f"Registrado {minutos_totais} minutos de dedicação para @{usr_atual}!")
                            st.rerun()

        with col_cr3:
            conn_c2 = get_connection()
            cursor_c2 = conn_c2.cursor()
            cursor_c2.execute("SELECT inicio, segundos_acumulados, status FROM cronometro_ativo_db WHERE username = ? AND projeto_id = ?", (usr_atual, proj_id))
            meu_timer = cursor_c2.fetchone()
            conn_c2.close()
            
            if meu_timer:
                ini_s, seg_a, st_u = meu_timer
                secs_vivos = seg_a
                if st_u == 'rodando' and ini_s:
                    secs_vivos += int((datetime.now() - datetime.strptime(ini_s, '%Y-%m-%d %H:%M:%S')).total_seconds())
                
                h = secs_vivos // 3600
                m = (secs_vivos % 3600) // 60
                s = secs_vivos % 60
                status_label = "🔴 Em andamento" if st_u == 'rodando' else "⏸️ Pausado"
                st.markdown(f"<span style='color: #4ade80; font-weight: 700; font-size: 0.95rem;'>{status_label}: {h:02d}:{m:02d}:{s:02d}</span>", unsafe_allow_html=True)

    render_cronometro_vivo(p_id, p_num)

    status_list = ['Em Aberto', 'Em Andamento', 'Pendente', 'Finalizado']
    
    tabs_labels = [
        '📊 Status & BA', 
        '☑️ Checklist', 
        '📎 Anexos',
        '💬 Notas & Observações', 
        '✏️ Editar Dados', 
        '🗑️ Excluir'
    ]
    
    if not isinstance(st.session_state.active_tab_modal, int) or st.session_state.active_tab_modal >= len(tabs_labels):
        st.session_state.active_tab_modal = 0

    if HAS_SAC:
        tab_selecionada_modal = sac.tabs(
            [sac.TabsItem(label=t) for t in tabs_labels],
            index=st.session_state.active_tab_modal,
            align='start',
            variant='default',
            color='blue',
            key=f'sac_modal_tabs_{p_id}'
        )
        label_to_idx = {t: i for i, t in enumerate(tabs_labels)}
        st.session_state.active_tab_modal = label_to_idx.get(tab_selecionada_modal, st.session_state.active_tab_modal)
        idx_tab_atual = st.session_state.active_tab_modal
    else:
        tabs_gerenciar = st.tabs(tabs_labels)
        idx_tab_atual = st.session_state.active_tab_modal

    def render_tab_status():
        col_s1, col_s2 = st.columns(2)
        with col_s1:
            novo_status = st.selectbox('Situação Atual', status_list, index=status_list.index(p_sit), key=f'modal_status_{p_id}')
        with col_s2:
            novo_ba = st.text_input('Número da BA (Boletim)', value=p_ba, key=f'modal_ba_{p_id}')

        motivo_input = p_motivo
        if novo_status == 'Pendente':
            motivo_input = st.text_input('Motivo da Pendência (Obrigatório):', value=p_motivo, key=f'modal_motivo_{p_id}')

        if st.button('Salvar Alterações de Status/BA', key=f'btn_save_status_{p_id}', use_container_width=True):
            chk_items = carregar_checklist(p_id)
            todos_concluidos = all(item[2] == 1 for item in chk_items)

            if novo_status == 'Finalizado' and not todos_concluidos:
                st.error('❌ Impossível Finalizar! Todos os itens do checklist precisam estar marcados.')
            elif novo_status == 'Pendente' and not motivo_input.strip():
                st.error('❌ Especifique o motivo da pendência.')
            else:
                conn = get_connection()
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE projetos 
                    SET situacao = ?, motivo_pendencia = ?, ba = ? 
                    WHERE id = ?
                """, (novo_status, motivo_input if novo_status == 'Pendente' else '', novo_ba, p_id))
                conn.commit()
                conn.close()
                registrar_log(f"Projeto '{p_num}' alterou status de '{p_sit}' para '{novo_status}'.", acao='ATUALIZAR_STATUS', detalhes=f"BA: {novo_ba}")
                st.success('Atualizado com sucesso!')
                st.session_state.modal_projeto_id = None
                st.rerun()

    def render_tab_checklist():
        st.markdown('**Critérios de Conclusão do Projeto:**')
        chk_items = carregar_checklist(p_id)
        novos_estados = {}

        if chk_items and HAS_REPORTLAB:
            pdf_chk_bytes = gerar_pdf_checklist(p_num, chk_items)
            st.download_button(
                '📄 Exportar Checklist em PDF',
                data=pdf_chk_bytes,
                file_name=f'checklist_{p_num.replace(" ", "_")}.pdf',
                mime='application/pdf',
                key=f'btn_dl_chk_pdf_{p_id}'
            )

        for idx_c, (chk_id, item_nome, concluido, ordem_val) in enumerate(chk_items):
            col_ordem, col_chk, col_atribuir, col_del = st.columns([0.14, 0.56, 0.18, 0.12])
            
            with col_ordem:
                sub_up, sub_down = st.columns(2)
                with sub_up:
                    if idx_c > 0:
                        if st.button('▲', key=f'up_chk_{chk_id}', help='Mover item para cima', use_container_width=True):
                            prev_chk_id, _, _, prev_ordem = chk_items[idx_c - 1]
                            conn = get_connection()
                            cursor = conn.cursor()
                            cursor.execute('UPDATE checklists SET ordem = ? WHERE id = ?', (prev_ordem, chk_id))
                            cursor.execute('UPDATE checklists SET ordem = ? WHERE id = ?', (ordem_val, prev_chk_id))
                            conn.commit()
                            conn.close()
                            st.session_state.active_tab_modal = 1
                            st.rerun()
                with sub_down:
                    if idx_c < len(chk_items) - 1:
                        if st.button('▼', key=f'down_chk_{chk_id}', help='Mover item para baixo', use_container_width=True):
                            next_chk_id, _, _, next_ordem = chk_items[idx_c + 1]
                            conn = get_connection()
                            cursor = conn.cursor()
                            cursor.execute('UPDATE checklists SET ordem = ? WHERE id = ?', (next_ordem, chk_id))
                            cursor.execute('UPDATE checklists SET ordem = ? WHERE id = ?', (ordem_val, next_chk_id))
                            conn.commit()
                            conn.close()
                            st.session_state.active_tab_modal = 1
                            st.rerun()

            with col_chk:
                is_checked = st.checkbox(item_nome, value=bool(concluido), key=f'modal_chk_{p_id}_{chk_id}')
                novos_estados[chk_id] = 1 if is_checked else 0

            with col_atribuir:
                anexos_item = [anx for anx in carregar_anexos_projeto(p_id) if anx[1] == chk_id]
                qtd_anx_item = len(anexos_item)
                
                with st.popover(f"📎 ({qtd_anx_item})", help="Anexar arquivos ou visualizar"):
                    st.markdown(f"**Anexos do item:** `{item_nome[:30]}...`")
                    file_chk_up = st.file_uploader("Enviar arquivo", key=f"file_chk_upload_{chk_id}")
                    if file_chk_up:
                        if st.button("Salvar Anexo no Item", key=f"btn_save_chk_anx_{chk_id}", use_container_width=True):
                            conn = get_connection()
                            cursor = conn.cursor()
                            cursor.execute("""
                                INSERT INTO anexos (projeto_id, checklist_id, nome_arquivo, dados_arquivo, tipo_arquivo, data_upload)
                                VALUES (?, ?, ?, ?, ?, ?)
                            """, (p_id, chk_id, file_chk_up.name, file_chk_up.getvalue(), file_chk_up.type, datetime.now().strftime('%d-%m-%Y %H:%M')))
                            conn.commit()
                            conn.close()
                            st.success("Anexado com sucesso!")
                            st.rerun()
                    
                    if anexos_item:
                        st.markdown("---")
                        st.markdown("**Arquivos anexados:**")
                        for anx_id, _, an_nome, an_dados, an_tipo, an_data in anexos_item:
                            col_dl, col_rm = st.columns([0.7, 0.3])
                            with col_dl:
                                st.download_button("👁️ Baixar", data=an_dados, file_name=an_nome, mime=an_tipo or "application/octet-stream", key=f"dl_anx_{anx_id}", use_container_width=True)
                            with col_rm:
                                if st.button("🗑️", key=f"rm_anx_{anx_id}", use_container_width=True):
                                    conn = get_connection()
                                    cursor = conn.cursor()
                                    cursor.execute("DELETE FROM anexos WHERE id = ?", (anx_id,))
                                    conn.commit()
                                    conn.close()
                                    st.rerun()

            with col_del:
                if st.button('🗑️', key=f'del_chk_{chk_id}', help='Excluir item', use_container_width=True):
                    conn = get_connection()
                    cursor = conn.cursor()
                    cursor.execute('DELETE FROM checklists WHERE id = ?', (chk_id,))
                    conn.commit()
                    conn.close()
                    registrar_log(f"Item removido do checklist do Projeto '{p_num}'", acao='EXCLUIR_CHECKLIST')
                    st.session_state.active_tab_modal = 1
                    st.rerun()

        st.markdown('---')
        
        with st.form(key=f'form_add_chk_{p_id}', clear_on_submit=True):
            novo_item_chk = st.text_area('Adicionar novo item (suporta textos longos):', placeholder='Ex: Empenhamento da Folha...')
            submitted_chk = st.form_submit_button('Adicionar Item', use_container_width=True)
            
            if submitted_chk:
                if novo_item_chk.strip():
                    conn = get_connection()
                    cursor = conn.cursor()
                    cursor.execute('SELECT COALESCE(MAX(ordem), 0) + 1 FROM checklists WHERE projeto_id = ?', (p_id,))
                    nova_ordem = cursor.fetchone()[0]
                    cursor.execute('INSERT INTO checklists (projeto_id, item, concluido, ordem) VALUES (?, ?, 0, ?)', (p_id, novo_item_chk.strip(), nova_ordem))
                    conn.commit()
                    conn.close()
                    registrar_log(f"Novo item adicionado ao checklist do Projeto '{p_num}'", acao='CRIAR_CHECKLIST', detalhes=novo_item_chk.strip()[:50])
                    st.session_state.active_tab_modal = 1
                    st.success('Item adicionado com sucesso!')
                    st.rerun()
                else:
                    st.warning('Informe o nome do item.')

        if st.button('Salvar Conclusões do Checklist', key=f'modal_btn_save_chk_{p_id}', use_container_width=True):
            conn = get_connection()
            cursor = conn.cursor()
            for chk_id, val in novos_estados.items():
                cursor.execute('UPDATE checklists SET concluido = ? WHERE id = ?', (val, chk_id))
            conn.commit()
            conn.close()
            registrar_log(f"Conclusões do checklist salvas no Projeto '{p_num}'", acao='ATUALIZAR_CHECKLIST')
            st.success('Checklist salvo com sucesso!')
            st.session_state.modal_projeto_id = None
            st.rerun()

    def render_tab_anexos():
        st.markdown('### 📎 Central de Anexos do Projeto')
        st.markdown('Gerencie todos os arquivos gerais e comprovantes do projeto.')

        with st.form(key=f"form_upload_geral_anexo_{p_id}", clear_on_submit=True):
            file_geral = st.file_uploader("Selecionar arquivo para upload geral no projeto:", key=f"uploader_geral_{p_id}")
            btn_up_geral = st.form_submit_button("Enviar Anexo Geral", use_container_width=True)
            
            if btn_up_geral:
                if file_geral:
                    conn = get_connection()
                    cursor = conn.cursor()
                    cursor.execute("""
                        INSERT INTO anexos (projeto_id, checklist_id, nome_arquivo, dados_arquivo, tipo_arquivo, data_upload)
                        VALUES (?, NULL, ?, ?, ?, ?)
                    """, (p_id, file_geral.name, file_geral.getvalue(), file_geral.type, datetime.now().strftime('%d-%m-%Y %H:%M')))
                    conn.commit()
                    conn.close()
                    st.success("Anexo enviado com sucesso!")
                    st.rerun()
                else:
                    st.warning("Selecione um arquivo primeiro.")

        st.markdown('---')
        st.markdown('**Lista de Anexos Armazenados:**')
        anexos_proj = carregar_anexos_projeto(p_id)
        
        if anexos_proj:
            for anx_id, chk_ref_id, an_nome, an_dados, an_tipo, an_data in anexos_proj:
                origem_txt = "📁 Geral do Projeto"
                if chk_ref_id:
                    conn = get_connection()
                    cursor = conn.cursor()
                    cursor.execute("SELECT item FROM checklists WHERE id = ?", (chk_ref_id,))
                    res_chk = cursor.fetchone()
                    conn.close()
                    if res_chk:
                        origem_txt = f"☑️ Checklist: {res_chk[0][:30]}..."

                col_det, col_down, col_del = st.columns([0.5, 0.3, 0.2])
                with col_det:
                    st.markdown(f"**{an_nome}**<br><span style='font-size: 0.75rem; color: #94a3b8;'>{origem_txt} &bull; {an_data}</span>", unsafe_allow_html=True)
                with col_down:
                    st.download_button("👁️ Baixar / Ver", data=an_dados, file_name=an_nome, mime=an_tipo or "application/octet-stream", key=f"dl_geral_{anx_id}", use_container_width=True)
                with col_del:
                    if st.button("🗑️ Excluir", key=f"del_geral_{anx_id}", use_container_width=True):
                        conn = get_connection()
                        cursor = conn.cursor()
                        cursor.execute("DELETE FROM anexos WHERE id = ?", (anx_id,))
                        conn.commit()
                        conn.close()
                        st.success("Removido!")
                        st.rerun()
                st.markdown("---")
        else:
            st.info("Nenhum anexo registrado neste projeto.")

    def render_tab_notas():
        st.markdown('**Histórico de Notas:**')
        comentarios = carregar_comentarios(p_id)
        if comentarios:
            for c_id, autor, texto, data in comentarios:
                col_n1, col_n2 = st.columns([0.9, 0.1])
                with col_n1:
                    st.info(f"**{autor}** em {data}:\n\n{texto}")
                with col_n2:
                    if st.session_state.perfil_logado == 'Administrador':
                        if st.button('🗑️', key=f'del_nota_{c_id}'):
                            conn = get_connection()
                            cursor = conn.cursor()
                            cursor.execute('DELETE FROM comentarios WHERE id = ?', (c_id,))
                            conn.commit()
                            conn.close()
                            registrar_log(f"Nota removida do Projeto '{p_num}'", acao='EXCLUIR_NOTA')
                            st.session_state.active_tab_modal = 3
                            st.rerun()
        else:
            st.caption('Nenhuma nota registrada.')

        st.markdown('---')
        autor_cmt = st.text_input('Seu Nome / Autor', value=st.session_state.usuario_logado, key=f'modal_autor_{p_id}')
        texto_cmt = st.text_area('Escrever observação:', key=f'modal_texto_{p_id}')

        st.markdown('**Notificar Usuários Específicos:**')
        busca_usr = st.text_input('🔍 Buscar Usuário para Notificar', key=f'busca_usr_{p_id}', placeholder='Digite para filtrar...')
        usuarios_sistema = carregar_usuarios_sistema()

        if busca_usr.strip():
            usuarios_sistema = [u for u in usuarios_sistema if busca_usr.lower() in u.lower()]

        usuarios_selecionados = []
        for user_sys in usuarios_sistema:
            if user_sys != st.session_state.usuario_logado:
                if st.checkbox(f'Notificar @{user_sys}', key=f'notif_usr_{p_id}_{user_sys}'):
                    usuarios_selecionados.append(user_sys)

        if st.button('Publicar Nota & Notificar', key=f'modal_btn_cmt_{p_id}', use_container_width=True):
            if autor_cmt.strip() and texto_cmt.strip():
                conn = get_connection()
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO comentarios (projeto_id, autor, texto, data)
                    VALUES (?, ?, ?, ?)
                """, (p_id, autor_cmt.strip(), texto_cmt.strip(), datetime.now().strftime('%d-%m-%Y %H:%M')))

                data_atual = datetime.now().strftime('%d-%m-%Y %H:%M')
                msg_notif = f"Nova nota no Projeto {p_num} por {autor_cmt.strip()}: '{texto_cmt.strip()[:50]}...'"
                for dest in usuarios_selecionados:
                    cursor.execute("""
                        INSERT INTO notificacoes (projeto_id, destinatario, remetente, mensagem, data, lida)
                        VALUES (?, ?, ?, ?, ?, 0)
                    """, (p_id, dest, st.session_state.usuario_logado, msg_notif, data_atual))

                conn.commit()
                conn.close()
                registrar_log(f"Nota criada no Projeto '{p_num}' com notificação para: {usuarios_selecionados}", acao='CRIAR_NOTA', detalhes=texto_cmt.strip())
                st.success('Nota publicada e notificações enviadas!')
                st.session_state.modal_projeto_id = None
                st.rerun()
            else:
                st.warning('Preencha a nota.')

    def render_tab_edit():
        mod_list_edit = carregar_modulos()
        mod_dict_edit = {m[1]: m[0] for m in mod_list_edit}
        an_list_edit = carregar_analistas()
        an_dict_edit = {a[1]: a[0] for a in an_list_edit}

        edit_num_proj = st.text_input('Número do Projeto', value=p_num, key=f'modal_edit_num_{p_id}')
        edit_pipefy = st.text_input('Link do Pipefy', value=p_pipefy or '', key=f'modal_edit_pipefy_{p_id}')

        state_emails_key = f'emails_list_state_{p_id}'
        if state_emails_key not in st.session_state:
            st.session_state[state_emails_key] = [e.strip() for e in (p_emails_str or '').split(',') if e.strip()]

        col_em_inp, col_em_btn = st.columns([0.75, 0.25])
        with col_em_inp:
            novo_email_input = st.text_input('Adicionar novo e-mail:', key=f'novo_email_inp_{p_id}', placeholder='ex: cliente@email.com', label_visibility='collapsed')
        with col_em_btn:
            btn_inc_email = st.button('Incluir E-mail', key=f'btn_add_email_{p_id}', use_container_width=True)

        if btn_inc_email:
            email_limpo = novo_email_input.strip()
            if email_limpo and '@' in email_limpo:
                if email_limpo not in st.session_state[state_emails_key]:
                    st.session_state[state_emails_key].append(email_limpo)
                    st.success(f"E-mail {email_limpo} incluído com sucesso!")
                    st.rerun()
            else:
                st.warning('Digite um e-mail válido contendo "@".')

        st.markdown('**E-mails Envolvidos no Projeto:**')
        if st.session_state[state_emails_key]:
            for idx_em, em_val in enumerate(st.session_state[state_emails_key]):
                col_em_tag, col_em_del = st.columns([0.8, 0.2])
                with col_em_tag:
                    st.markdown(f"""
                        <span style="background: #1e293b; color: #38bdf8; border: 1px solid #334155; padding: 6px 12px; border-radius: 16px; font-size: 0.85rem; display: inline-flex; align-items: center; gap: 6px; margin-bottom: 6px;">
                            <i class="fa-solid fa-envelope"></i> {em_val}
                        </span>
                    """, unsafe_allow_html=True)
                with col_em_del:
                    if st.button('🗑️', key=f'rem_em_edit_{p_id}_{idx_em}', help=f'Remover {em_val}'):
                        st.session_state[state_emails_key].pop(idx_em)
                        st.rerun()
        else:
            st.caption('Nenhum e-mail adicionado ainda.')

        dt_val = datetime.strptime(p_data_prev, '%Y-%m-%d').date() if p_data_prev else datetime.today().date()
        edit_data_prev = st.date_input('Data Prevista de Início', value=dt_val, format='DD/MM/YYYY', key=f'modal_edit_dt_{p_id}')

        mod_atual_nome = next((m[1] for m in mod_list_edit if m[0] == p_mod_id), list(mod_dict_edit.keys())[0] if mod_dict_edit else '')
        edit_modulo = st.selectbox(
            'Módulo',
            options=list(mod_dict_edit.keys()),
            index=list(mod_dict_edit.keys()).index(mod_atual_nome) if mod_atual_nome in mod_dict_edit else 0,
            key=f'modal_edit_mod_{p_id}',
        )

        an_atual_nome = next((a[1] for a in an_list_edit if a[0] == p_analista_id), list(an_dict_edit.keys())[0] if an_dict_edit else '')
        edit_analista = st.selectbox(
            'Analista Responsável',
            options=list(an_dict_edit.keys()),
            index=list(an_dict_edit.keys()).index(an_atual_nome) if an_atual_nome in an_dict_edit else 0,
            key=f'modal_edit_an_{p_id}',
        )

        edit_gestor = st.text_input('Gestor de Contrato', value=p_gestor, key=f'modal_edit_gestor_{p_id}')
        edit_tel_g = st.text_input('Telefone Gestor', value=p_tel_g, key=f'modal_edit_telg_{p_id}')
        edit_resp = st.text_input('Responsável Técnico', value=p_resp, key=f'modal_edit_resp_{p_id}')
        edit_tel_r = st.text_input('Telefone Resp.', value=p_tel_r, key=f'modal_edit_telr_{p_id}')

        if st.session_state.perfil_logado == 'Administrador':
            st.markdown('---')
            st.markdown('##### ⏱️ Ajuste Manual de Horas/Minutos (Administrador)')
            minutos_ajuste = st.number_input('Adicionar minutos extras dedicados ao projeto:', min_value=0, step=10, key=f'admin_min_ajuste_{p_id}')
            if st.button('Salvar Minutos Manuais', key=f'btn_admin_add_min_{p_id}', use_container_width=True):
                if minutos_ajuste > 0:
                    conn_adm = get_connection()
                    cursor_adm = conn_adm.cursor()
                    cursor_adm.execute("""
                        INSERT INTO tempo_projetos (projeto_id, usuario, data_registro, minutos_gastos)
                        VALUES (?, ?, ?, ?)
                    """, (p_id, f"{st.session_state.usuario_logado} (Admin Ajuste)", datetime.now().strftime('%Y-%m-%d'), minutos_ajuste))
                    conn_adm.commit()
                    conn_adm.close()
                    registrar_log(f"Administrador adicionou manualmente {minutos_ajuste} minutos ao projeto {p_num}.", acao='AJUSTE_TEMPO_ADMIN')
                    st.success(f"Adicionado {minutos_ajuste} minutos ao projeto com sucesso!")
                    st.rerun()

        if st.button('Salvar Alterações Cadastrais', key=f'modal_btn_save_edit_{p_id}', use_container_width=True):
            if not edit_num_proj.strip():
                st.error("O 'Número do Projeto' é obrigatório.")
            else:
                try:
                    conn = get_connection()
                    cursor = conn.cursor()
                    emails_str_final = ', '.join(st.session_state[state_emails_key])
                    cursor.execute("""
                        UPDATE projetos 
                        SET num_projeto = ?, pipefy_link = ?, emails_lista = ?, modulo_id = ?, analista_id = ?, gestor = ?, tel_gestor = ?, resp = ?, tel_resp = ?, data_prevista = ?
                        WHERE id = ?
                    """, (
                        edit_num_proj.strip(),
                        edit_pipefy,
                        emails_str_final,
                        mod_dict_edit.get(edit_modulo),
                        an_dict_edit.get(edit_analista),
                        edit_gestor,
                        edit_tel_g,
                        edit_resp,
                        edit_tel_r,
                        edit_data_prev.strftime('%Y-%m-%d'),
                        p_id,
                    ))
                    conn.commit()
                    conn.close()
                    registrar_log(f"Projeto ID {p_id} editado. Número: '{edit_num_proj.strip()}'", acao='EDITAR_PROJETO')
                    st.success('Atualizado com sucesso!')
                    st.session_state.modal_projeto_id = None
                    st.session_state.active_tab_modal = 0
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.error(f"Já existe outro projeto cadastrado como '{edit_num_proj.strip()}'.")

    def render_tab_del():
        analista_usr_id, analista_usr_nome = carregar_analista_do_usuario(st.session_state.usuario_logado)
        pode_excluir = (
            st.session_state.perfil_logado == 'Administrador'
            or (analista_usr_id is not None and p_analista_id == analista_usr_id)
        )

        if pode_excluir:
            st.warning('⚠️ Atenção: Esta ação excluirá permanentemente o projeto.')
            confirmar_del = st.checkbox('Confirmo a exclusão definitiva', key=f'modal_chk_del_{p_id}')
            if st.button('Excluir Projeto', key=f'modal_btn_del_{p_id}', use_container_width=True):
                if confirmar_del:
                    conn = get_connection()
                    cursor = conn.cursor()
                    cursor.execute('DELETE FROM projetos WHERE id = ?', (p_id,))
                    conn.commit()
                    conn.close()
                    registrar_log(f"Projeto '{p_num}' foi excluído definitivamente.", acao='EXCLUIR_PROJETO', detalhes=f"ID: {p_id}")
                    st.session_state.modal_projeto_id = None
                    st.success('Projeto excluído!')
                    st.rerun()
                else:
                    st.error('Marque a caixa de confirmação.')
        else:
            st.error('🔒 Permissão Negada: Como Usuário Normal, você só pode excluir projetos dos quais você é o Analista responsável.')

    if not HAS_SAC:
        with tabs_gerenciar[0]: render_tab_status()
        with tabs_gerenciar[1]: render_tab_checklist()
        with tabs_gerenciar[2]: render_tab_anexos()
        with tabs_gerenciar[3]: render_tab_notas()
        with tabs_gerenciar[4]: render_tab_edit()
        with tabs_gerenciar[5]: render_tab_del()
    else:
        if idx_tab_atual == 0: render_tab_status()
        elif idx_tab_atual == 1: render_tab_checklist()
        elif idx_tab_atual == 2: render_tab_anexos()
        elif idx_tab_atual == 3: render_tab_notas()
        elif idx_tab_atual == 4: render_tab_edit()
        elif idx_tab_atual == 5: render_tab_del()

# ==================== BARRA LATERAL ESTILIZADA ====================
st.sidebar.markdown(f"""
    <div style="background: rgba(15,23,42,0.6); padding: 12px; border-radius: 10px; margin-bottom: 15px; border: 1px solid #334155;">
        <div style="font-size: 0.85rem; color: #94a3b8; font-weight: 600;"><i class="fa-solid fa-user-gear"></i> USUÁRIO CONECTADO</div>
        <div style="font-size: 1rem; font-weight: 700; color: #38bdf8; margin-top: 2px;">@{st.session_state.usuario_logado}</div>
        <div style="margin-top: 6px;"><span class="badge-perfil">{st.session_state.perfil_logado}</span></div>
    </div>
""", unsafe_allow_html=True)

# NOTIFICAÇÕES
conn = get_connection()
cursor = conn.cursor()
cursor.execute("""
    SELECT COUNT(*) FROM notificacoes n
    INNER JOIN projetos p ON n.projeto_id = p.id
    WHERE n.destinatario = ? AND n.lida = 0
""", (st.session_state.usuario_logado,))
qtd_nao_lidas = cursor.fetchone()[0]
conn.close()

titulo_notificacoes = f'🔔 Notificações ({qtd_nao_lidas})' if qtd_nao_lidas > 0 else '🔔 Notificações'

with st.sidebar.expander(titulo_notificacoes):
    tab_nlidas, tab_lidas, tab_enviadas = st.tabs(['📥 Não Lidas', '✅ Lidas', '📤 Enviadas'])

    conn = get_connection()
    cursor = conn.cursor()

    with tab_nlidas:
        cursor.execute("""
            SELECT n.id, n.mensagem, n.data, n.projeto_id FROM notificacoes n
            INNER JOIN projetos p ON n.projeto_id = p.id
            WHERE n.destinatario = ? AND n.lida = 0 ORDER BY n.id DESC
        """, (st.session_state.usuario_logado,))
        notif_nlidas = cursor.fetchall()

        if notif_nlidas:
            for n_id, n_msg, n_data, n_pid in notif_nlidas:
                st.markdown(f"📩 **[{n_data}]**\n{n_msg}")
                col_n1, col_n2 = st.columns(2)
                with col_n1:
                    if st.button('Marcar Lida', key=f'ler_notif_{n_id}'):
                        conn_u = get_connection()
                        cursor_u = conn_u.cursor()
                        cursor_u.execute('UPDATE notificacoes SET lida = 1 WHERE id = ?', (n_id,))
                        conn_u.commit()
                        conn_u.close()
                        st.rerun()
                with col_n2:
                    if st.button('Ver Projeto', key=f'ver_notif_p_{n_id}'):
                        st.session_state.show_historico_modal = False
                        st.session_state.modal_historico_id = None
                        st.session_state.modal_projeto_id = n_pid
                        st.rerun()
                st.markdown('---')
        else:
            st.caption('Nenhuma notificação não lida.')

    with tab_lidas:
        cursor.execute("""
            SELECT n.id, n.mensagem, n.data, n.projeto_id FROM notificacoes n
            INNER JOIN projetos p ON n.projeto_id = p.id
            WHERE n.destinatario = ? AND n.lida = 1 ORDER BY n.id DESC
        """, (st.session_state.usuario_logado,))
        notif_lidas = cursor.fetchall()

        if notif_lidas:
            for n_id, n_msg, n_data, n_pid in notif_lidas:
                st.markdown(f"✔️ **[{n_data}]**\n{n_msg}")
                if st.button('Ver Projeto', key=f'ver_notif_lida_p_{n_id}'):
                    st.session_state.show_historico_modal = False
                    st.session_state.modal_historico_id = None
                    st.session_state.modal_projeto_id = n_pid
                    st.rerun()
                st.markdown('---')
        else:
            st.caption('Nenhuma notificação lida registrada.')

    with tab_enviadas:
        cursor.execute("""
            SELECT n.id, n.mensagem, n.data, n.projeto_id, n.destinatario FROM notificacoes n
            INNER JOIN projetos p ON n.projeto_id = p.id
            WHERE n.remetente = ? ORDER BY n.id DESC
        """, (st.session_state.usuario_logado,))
        notif_enviadas = cursor.fetchall()

        if notif_enviadas:
            for n_id, n_msg, n_data, n_pid, dest_usr in notif_enviadas:
                st.markdown(f"📤 Para **@{dest_usr}** em **[{n_data}]**\n{n_msg}")
                if st.button('Ver Projeto', key=f'ver_notif_env_p_{n_id}'):
                    st.session_state.show_historico_modal = False
                    st.session_state.modal_historico_id = None
                    st.session_state.modal_projeto_id = n_pid
                    st.rerun()
                st.markdown('---')
        else:
            st.caption('Nenhuma notificação enviada registrada.')

    conn.close()

with st.sidebar.expander('🔒 Redefinir Minha Senha'):
    with st.form('form_mudarsenha_propria'):
        senha_antiga = st.text_input('Senha Atual', type='password', key='pwd_antiga')
        senha_nova1 = st.text_input('Nova Senha', type='password', key='pwd_nova1')
        senha_nova2 = st.text_input('Confirmar Nova Senha', type='password', key='pwd_nova2')
        btn_mudar = st.form_submit_button('Atualizar Senha', use_container_width=True)

        if btn_mudar:
            if senha_nova1 != senha_nova2:
                st.error('As novas senhas não coincidem.')
            elif not senha_nova1.strip():
                st.error('A nova senha não pode ser vazia.')
            else:
                conn = get_connection()
                cursor = conn.cursor()
                cursor.execute('SELECT senha FROM usuarios WHERE username = ?', (st.session_state.usuario_logado,))
                atual_db = cursor.fetchone()[0]

                if atual_db != hash_senha(senha_antiga):
                    st.error('Senha atual incorreta.')
                else:
                    cursor.execute('UPDATE usuarios SET senha = ? WHERE username = ?', (hash_senha(senha_nova1), st.session_state.usuario_logado))
                    conn.commit()
                    conn.close()
                    registrar_log('Senha alterada com sucesso.', acao='REDEFINIR_SENHA')
                    st.success('Senha alterada com sucesso!')

if st.sidebar.button('Sair da Conta', use_container_width=True):
    registrar_log('Usuário deslogou do sistema.', acao='LOGOUT')
    st.session_state.usuario_logado = None
    st.session_state.perfil_logado = None
    st.session_state.modal_projeto_id = None
    st.session_state.modal_historico_id = None
    st.session_state.show_historico_modal = False
    st.session_state.active_tab_modal = 0
    atualizar_query_params()
    st.rerun()

st.sidebar.markdown('---')
st.sidebar.markdown('### <i class="fa-solid fa-sliders"></i> Configurações', unsafe_allow_html=True)

permissoes_user = (
    {'modulos': True, 'analistas': True, 'cadastrar': True, 'backup': True, 'acesso_db': True, 'dashboard': True, 'relatorios': True}
    if st.session_state.perfil_logado == 'Administrador'
    else carregar_permissoes_usuario(st.session_state.usuario_logado)
)

if st.session_state.perfil_logado == 'Administrador' or permissoes_user['modulos']:
    with st.sidebar.expander('🧩 Gerenciar Módulos'):
        novo_modulo = st.text_input('Nome do Módulo', placeholder='Cadastrar módulos', key='input_novo_modulo')
        if st.button('Adicionar Módulo', use_container_width=True, key='btn_add_modulo'):
            if novo_modulo.strip():
                try:
                    conn = get_connection()
                    cursor = conn.cursor()
                    cursor.execute('INSERT INTO modulos (nome) VALUES (?)', (novo_modulo.strip(),))
                    conn.commit()
                    conn.close()
                    registrar_log(f'Módulo cadastrado: {novo_modulo.strip()}', acao='CRIAR_MODULO')
                    st.success('Cadastrado!')
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.error('Já existe.')
            else:
                st.warning('Informe o nome.')
        st.caption('**Atuais:** ' + ', '.join([m[1] for m in carregar_modulos()]) or 'Nenhum')

if st.session_state.perfil_logado == 'Administrador' or permissoes_user['analistas']:
    with st.sidebar.expander('👥 Gerenciar Analistas'):
        novo_analista = st.text_input('Nome do Analista', key='input_novo_analista')
        if st.button('Adicionar Analista', use_container_width=True, key='btn_add_analista'):
            if novo_analista.strip():
                try:
                    conn = get_connection()
                    cursor = conn.cursor()
                    cursor.execute('INSERT INTO analistas (nome) VALUES (?)', (novo_analista.strip(),))
                    conn.commit()
                    conn.close()
                    registrar_log(f'Analista cadastrado: {novo_analista.strip()}', acao='CRIAR_ANALISTA')
                    st.success('Cadastrado!')
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.error('Já existe.')
            else:
                st.warning('Informe o nome.')
        st.caption('**Atuais:** ' + ', '.join([a[1] for a in carregar_analistas()]) or 'Nenhum')

if st.session_state.perfil_logado == 'Administrador':
    with st.sidebar.expander('🔑 Gerenciar Perfis & Usuários'):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT username FROM usuarios WHERE username != "admin"')
        usernames_list = [u[0] for u in cursor.fetchall()]
        conn.close()

        if usernames_list:
            sub_g_tab1, sub_g_tab2 = st.tabs(['⚙️ Configurar Usuário', '📋 Lista Geral de Usuários'])

            with sub_g_tab1:
                sel_user_mod = st.selectbox('Selecionar Usuário', options=usernames_list, key='sel_user_mod_config')
                
                conn = get_connection()
                cursor = conn.cursor()
                cursor.execute('SELECT perfil, analista_id FROM usuarios WHERE username = ?', (sel_user_mod,))
                u_perf, u_an_id = cursor.fetchone()
                conn.close()

                analistas_opts = [(-1, 'Nenhum Analista Vinculado')] + carregar_analistas()
                idx_an = 0
                if u_an_id:
                    for idx, a_tuple in enumerate(analistas_opts):
                        if a_tuple[0] == u_an_id:
                            idx_an = idx
                            break

                novo_p = st.selectbox(
                    'Perfil de Acesso',
                    ['Pendente', 'Usuário Normal', 'Administrador'],
                    index=(['Pendente', 'Usuário Normal', 'Administrador'].index(u_perf if u_perf else 'Pendente')),
                    key=f'sel_perfil_{sel_user_mod}',
                )

                sel_analista_user = st.selectbox(
                    'Vincular ao Analista',
                    options=analistas_opts,
                    format_func=lambda x: x[1],
                    index=idx_an,
                    key=f'sel_an_user_{sel_user_mod}',
                )

                perm_u = carregar_permissoes_usuario(sel_user_mod)
                st.markdown('**Módulos / Funções Liberadas:**')
                chk_mod = st.checkbox('🧩 Gerenciar Módulos', value=perm_u['modulos'], key=f'perm_mod_{sel_user_mod}')
                chk_an = st.checkbox('👥 Gerenciar Analistas', value=perm_u['analistas'], key=f'perm_an_{sel_user_mod}')
                chk_cad = st.checkbox('➕ Cadastrar Projetos', value=perm_u['cadastrar'], key=f'perm_cad_{sel_user_mod}')
                chk_dash = st.checkbox('📊 Dashboard Analytics', value=perm_u['dashboard'], key=f'perm_dash_{sel_user_mod}')
                chk_rel = st.checkbox('📈 Relatórios Avançados', value=perm_u['relatorios'], key=f'perm_rel_{sel_user_mod}')
                chk_bak = st.checkbox('📋 Auditoria de Logs', value=perm_u['backup'], key=f'perm_bak_{sel_user_mod}')
                chk_db = st.checkbox('💻 Acesso ao DB (Terminal)', value=perm_u['acesso_db'], key=f'perm_db_{sel_user_mod}')

                col_u1, col_u2 = st.columns(2)
                with col_u1:
                    if st.button('Salvar Alterações', key=f'btn_salvar_p_{sel_user_mod}', use_container_width=True):
                        p_final = None if novo_p == 'Pendente' else novo_p
                        an_final_id = sel_analista_user[0] if sel_analista_user[0] != -1 else None

                        conn = get_connection()
                        cursor = conn.cursor()
                        cursor.execute(
                            'UPDATE usuarios SET perfil = ?, analista_id = ? WHERE username = ?',
                            (p_final, an_final_id, sel_user_mod),
                        )

                        cursor.execute("""
                            INSERT INTO permissoes_usuarios (username, gerenciar_modulos, gerenciar_analistas, cadastrar_projetos, backup_auditoria, acesso_db, acesso_dashboard, acesso_relatorios)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(username) DO UPDATE SET
                                gerenciar_modulos=excluded.gerenciar_modulos,
                                gerenciar_analistas=excluded.gerenciar_analistas,
                                cadastrar_projetos=excluded.cadastrar_projetos,
                                backup_auditoria=excluded.backup_auditoria,
                                acesso_db=excluded.acesso_db,
                                acesso_dashboard=excluded.acesso_dashboard,
                                acesso_relatorios=excluded.acesso_relatorios
                        """, (sel_user_mod, 1 if chk_mod else 0, 1 if chk_an else 0, 1 if chk_cad else 0, 1 if chk_bak else 0, 1 if chk_db else 0, 1 if chk_dash else 0, 1 if chk_rel else 0))

                        conn.commit()
                        conn.close()
                        registrar_log(f"Permissões e perfil do usuário {sel_user_mod} atualizadas.", acao='ALTERAR_PERMISSOES')
                        st.success(f'Configurações de {sel_user_mod} atualizadas!')
                        st.rerun()

                with col_u2:
                    if st.button('🗑️ Excluir User', key=f'btn_del_u_{sel_user_mod}', use_container_width=True):
                        conn = get_connection()
                        cursor = conn.cursor()
                        cursor.execute('DELETE FROM usuarios WHERE username = ?', (sel_user_mod,))
                        cursor.execute('DELETE FROM permissoes_usuarios WHERE username = ?', (sel_user_mod,))
                        conn.commit()
                        conn.close()
                        registrar_log(f"Usuário {sel_user_mod} excluído do sistema.", acao='EXCLUIR_USUARIO')
                        st.success(f'Usuário {sel_user_mod} excluído!')
                        st.rerun()

                st.markdown('---')
                with st.expander(f'🔑 Redefinir Senha do Usuário (@{sel_user_mod})'):
                    with st.form(key=f'form_admin_reset_pwd_{sel_user_mod}'):
                        nova_senha_admin = st.text_input('Nova Senha para o Usuário', type='password', key=f'pwd_adm_new_{sel_user_mod}')
                        nova_senha_admin_conf = st.text_input('Confirmar Nova Senha', type='password', key=f'pwd_adm_new_conf_{sel_user_mod}')
                        btn_reset_pwd = st.form_submit_button('Redefinir Senha do Usuário', use_container_width=True)

                        if btn_reset_pwd:
                            if not nova_senha_admin.strip():
                                st.error('A nova senha não pode estar em branco.')
                            elif nova_senha_admin != nova_senha_admin_conf:
                                st.error('As senhas digitadas não coincidem.')
                            else:
                                conn = get_connection()
                                cursor = conn.cursor()
                                cursor.execute('UPDATE usuarios SET senha = ? WHERE username = ?', (hash_senha(nova_senha_admin), sel_user_mod))
                                conn.commit()
                                conn.close()
                                registrar_log(f"Administrador redefiniu a senha do usuário @{sel_user_mod}.", acao='REDEFINIR_SENHA_ADMIN')
                                st.success(f'Senha do usuário @{sel_user_mod} redefinida com sucesso!')

            with sub_g_tab2:
                st.markdown('##### 📋 Painel Analítico de Usuários e Atividade')
                conn = get_connection()
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT u.username, COALESCE(u.perfil, 'Pendente'), COALESCE(a.nome, 'Nenhum Vinculado'), u.ultimo_acesso, u.tempo_online_minutos 
                    FROM usuarios u 
                    LEFT JOIN analistas a ON u.analista_id = a.id
                    ORDER BY u.username
                """)
                t_users = cursor.fetchall()
                conn.close()

                lista_formatada_usuarios = []
                agora = datetime.now()
                for usr, perf, an_nome, ultimo_ac, tempo_min in t_users:
                    status_online = "⚪ Offline"
                    if ultimo_ac:
                        try:
                            dt_ult = datetime.strptime(ultimo_ac, '%Y-%m-%d %H:%M:%S')
                            if (agora - dt_ult).total_seconds() < 300:
                                status_online = "🟢 Online"
                        except Exception:
                            pass
                    
                    horas = tempo_min // 60
                    mins = tempo_min % 60
                    tempo_fmt = f"{horas}h {mins}m" if horas > 0 else f"{mins}m"

                    lista_formatada_usuarios.append({
                        'Usuário': f"@{usr}",
                        'Perfil': perf,
                        'Analista Vinculado': an_nome,
                        'Status': status_online,
                        'Tempo Total Online': tempo_fmt,
                        'Último Acesso': ultimo_ac or 'Nunca'
                    })

                df_t_users = pd.DataFrame(lista_formatada_usuarios)
                st.dataframe(df_t_users, use_container_width=True, hide_index=True)
        else:
            st.info('Nenhum outro usuário cadastrado.')

if st.session_state.perfil_logado == 'Administrador' or permissoes_user['backup']:
    with st.sidebar.expander('💾 Backup do Banco'):
        if os.path.exists(DB_NAME):
            with open(DB_NAME, 'rb') as f:
                db_data = f.read()
            st.download_button(
                label='📥 Baixar Banco (.db com Anexos)',
                data=db_data,
                file_name=f"backup_atende_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db",
                mime='application/x-sqlite3',
                use_container_width=True,
            )

if st.session_state.perfil_logado == 'Administrador' or permissoes_user['cadastrar']:
    with st.sidebar.expander('➕ Cadastrar Novo Projeto', expanded=False):
        modulos_list = carregar_modulos()
        modulos_dict = {m[1]: m[0] for m in modulos_list}

        analistas_list = carregar_analistas()
        analistas_dict = {a[1]: a[0] for a in analistas_list}

        an_vinculado_id, an_vinculado_nome = carregar_analista_do_usuario(st.session_state.usuario_logado)
        index_an_def = 0
        if an_vinculado_nome and an_vinculado_nome in analistas_dict:
            index_an_def = list(analistas_dict.keys()).index(an_vinculado_nome)

        if 'form_novo_num' not in st.session_state: st.session_state['form_novo_num'] = ''
        if 'form_novo_pipefy' not in st.session_state: st.session_state['form_novo_pipefy'] = ''
        if 'novo_emails_state' not in st.session_state: st.session_state['novo_emails_state'] = []
        if 'form_novo_gestor' not in st.session_state: st.session_state['form_novo_gestor'] = ''
        if 'form_novo_telg' not in st.session_state: st.session_state['form_novo_telg'] = ''
        if 'form_novo_resp' not in st.session_state: st.session_state['form_novo_resp'] = ''
        if 'form_novo_telr' not in st.session_state: st.session_state['form_novo_telr'] = ''
        if 'form_novo_ba' not in st.session_state: st.session_state['form_novo_ba'] = ''

        p_num = st.text_input('Número do Projeto :red[*]', placeholder='PRJ-2026-001', key='form_novo_num')
        p_pipefy = st.text_input('Link do Pipefy', placeholder='https://app.pipefy.com/...', key='form_novo_pipefy')
        
        col_cad_em1, col_cad_em2 = st.columns([0.72, 0.28])
        with col_cad_em1:
            novo_email_cad_inp = st.text_input('Adicionar e-mail:', key='novo_email_cad_text', placeholder='ex: analista@gov.br', label_visibility='collapsed')
        with col_cad_em2:
            if st.button('Incluir E-mail', key='btn_incluir_email_cad', use_container_width=True):
                e_clean = novo_email_cad_inp.strip()
                if e_clean and '@' in e_clean:
                    if e_clean not in st.session_state['novo_emails_state']:
                        st.session_state['novo_emails_state'].append(e_clean)
                        st.success(f"E-mail {e_clean} incluído!")
                        st.rerun()
                else:
                    st.warning('Digite um e-mail válido contendo "@".')

        st.markdown('**E-mails Envolvidos no Projeto:**')
        if st.session_state['novo_emails_state']:
            for idx_em, em_val in enumerate(st.session_state['novo_emails_state']):
                col_em_tag, col_em_del = st.columns([0.8, 0.2])
                with col_em_tag:
                    st.markdown(f"""
                        <span style="background: #1e293b; color: #38bdf8; border: 1px solid #334155; padding: 6px 12px; border-radius: 16px; font-size: 0.85rem; display: inline-flex; align-items: center; gap: 6px; margin-bottom: 6px;">
                            <i class="fa-solid fa-envelope"></i> {em_val}
                        </span>
                    """, unsafe_allow_html=True)
                with col_em_del:
                    if st.button('🗑️', key=f'rem_em_cad_{idx_em}', help=f'Remover {em_val}'):
                        st.session_state['novo_emails_state'].pop(idx_em)
                        st.rerun()
        else:
            st.caption('Nenhum e-mail adicionado.')

        p_data_prevista = st.date_input('Data Prevista de Início', value=datetime.today().date(), format='DD/MM/YYYY', key='novo_prj_dt')
        p_modulo_nome = st.selectbox('Módulo', options=list(modulos_dict.keys()) if modulos_dict else ['Cadastre um módulo primeiro'], key='novo_prj_mod')
        p_analista_nome = st.selectbox('Analista Responsável :red[*]', options=list(analistas_dict.keys()) if analistas_dict else ['Cadastre um analista primeiro'], index=index_an_def if analistas_dict else 0, key='novo_prj_an')

        p_gestor = st.text_input('Gestor de Contrato (Prefeitura)', key='form_novo_gestor')
        p_tel_gestor = st.text_input('Telefone do Gestor', key='form_novo_telg')
        p_resp = st.text_input('Responsável Técnico (Prefeitura)', key='form_novo_resp')
        p_tel_resp = st.text_input('Telefone do Responsável', key='form_novo_telr')
        p_ba = st.text_input('Número da BA', key='form_novo_ba')
        p_checklist_items = st.text_area('Checklist Inicial (um por linha)', value='Assinado a lista de treinamento?\nAssinado o boletim?\nAssinado os termos?\nFeito video de finalização do projeto?', key='novo_prj_chk')

        if st.button('Salvar Novo Projeto', use_container_width=True, key='btn_salvar_novo_projeto_def'):
            if not p_num.strip():
                st.error("O campo 'Número do Projeto' é obrigatório.")
            elif not analistas_dict:
                st.error('Cadastre pelo menos um analista.')
            else:
                try:
                    conn = get_connection()
                    cursor = conn.cursor()
                    emails_str_final = ', '.join(st.session_state['novo_emails_state'])
                    cursor.execute("""
                        INSERT INTO projetos (num_projeto, pipefy_link, emails_lista, modulo_id, analista_id, gestor, tel_gestor, resp, tel_resp, situacao, motivo_pendencia, ba, data_prevista)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'Em Aberto', '', ?, ?)
                    """, (
                        p_num.strip(),
                        p_pipefy,
                        emails_str_final,
                        modulos_dict.get(p_modulo_nome),
                        analistas_dict[p_analista_nome],
                        p_gestor,
                        p_tel_gestor,
                        p_resp,
                        p_tel_resp,
                        p_ba,
                        p_data_prevista.strftime('%Y-%m-%d'),
                    ))
                    proj_id = cursor.lastrowid

                    items = [i.strip() for i in p_checklist_items.split('\n') if i.strip()]
                    for idx_i, item in enumerate(items):
                        cursor.execute('INSERT INTO checklists (projeto_id, item, concluido, ordem) VALUES (?, ?, 0, ?)', (proj_id, item, idx_i))

                    conn.commit()
                    conn.close()
                    st.session_state['novo_emails_state'] = []
                    st.session_state['form_novo_num'] = ''
                    st.session_state['form_novo_pipefy'] = ''
                    st.session_state['form_novo_gestor'] = ''
                    st.session_state['form_novo_telg'] = ''
                    st.session_state['form_novo_resp'] = ''
                    st.session_state['form_novo_telr'] = ''
                    st.session_state['form_novo_ba'] = ''
                    registrar_log(f"Projeto '{p_num}' criado com sucesso.", acao='CRIAR_PROJETO')
                    st.success('Projeto criado com sucesso!')
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.error('Este número de projeto já existe.')

# ==================== CABEÇALHO ENTERPRISE FULL-WIDTH ====================
st.markdown(f"""
    <div class="app-header">
        <div class="header-content">
            <div class="header-title">
                <div class="header-title-icon">
                    <i class="fa-solid fa-layer-group"></i>
                </div>
                <div>
                    <h1>Sistema de Implantações</h1>
                    <p>Controle de projetos, cronogramas e operações</p>
                </div>
            </div>
            <div class="header-user-badge">
                <div class="user-info">
                    <span>Usuário Ativo</span>
                    <strong><i class="fa-solid fa-circle-user" style="color: #38bdf8; margin-right: 4px;"></i> @{st.session_state.usuario_logado}</strong>
                </div>
                <div>
                    <span class="badge-perfil"><i class="fa-solid fa-shield-halved"></i> {st.session_state.perfil_logado}</span>
                </div>
            </div>
        </div>
    </div>
""", unsafe_allow_html=True)

# ==================== NAVEGAÇÃO / ABAS PRINCIPAIS ====================
tabs_items_config = [
    ('Painel', 'kanban', True),
    ('Agenda', 'calendar-week', True),
    ('Relatório de Horas & Cronômetros', 'stopwatch', True),
    ('Relatórios Avançados', 'file-earmark-bar-graph', st.session_state.perfil_logado == 'Administrador' or permissoes_user['relatorios']),
    ('Dashboard Analytics', 'pie-chart', st.session_state.perfil_logado == 'Administrador' or permissoes_user['dashboard']),
    ('Auditoria de Logs', 'shield-lock', st.session_state.perfil_logado == 'Administrador' or permissoes_user['backup']),
    ('Acesso ao DB (Terminal)', 'terminal', st.session_state.perfil_logado == 'Administrador' or permissoes_user['acesso_db'])
]

tabs_visiveis = [t for t in tabs_items_config if t[2]]
tabs_labels_visiveis = [t[0] for t in tabs_visiveis]

if HAS_SAC:
    sac_items = [sac.TabsItem(label=t[0], icon=t[1]) for t in tabs_visiveis]
    
    tab_selecionada = sac.tabs(
        sac_items, 
        align='start', 
        variant='segmented', 
        color='blue', 
        key='main_navigation_tabs'
    )
    
    if 'ultima_aba_selecionada' not in st.session_state:
        st.session_state.ultima_aba_selecionada = tab_selecionada
    elif st.session_state.ultima_aba_selecionada != tab_selecionada:
        st.session_state.ultima_aba_selecionada = tab_selecionada
        st.session_state.modal_projeto_id = None
        st.session_state.modal_historico_id = None
        st.session_state.show_historico_modal = False

    opcao_aba_nome = tab_selecionada
else:
    abas = st.tabs([t[0] for t in tabs_visiveis])
    opcao_aba_nome = tabs_labels_visiveis[0]

# ==================== ABA 1: PAINEL KANBAN NATIVO INTERATIVO ====================
def render_painel_kanban():
    st.markdown('### <i class="fa-solid fa-border-all" style="color: #3b82f6;"></i> Painel Geral de Implantações', unsafe_allow_html=True)

    modulos_cadastrados = [m[1] for m in carregar_modulos()]
    analistas_cadastrados = [a[1] for a in carregar_analistas()]

    col_f_mod, col_f_an, col_f_dt1, col_f_dt2 = st.columns([2, 2, 1.5, 1.5])
    with col_f_mod:
        filtro_mod_kanban = st.multiselect('Módulos:', modulos_cadastrados, key='filtro_mod_kanban_input', placeholder='Todos')
    with col_f_an:
        filtro_an_kanban = st.multiselect('Analistas:', analistas_cadastrados, key='filtro_an_kanban_input', placeholder='Todos')
    with col_f_dt1:
        filtro_data_ini = st.date_input('Início Previsto (De):', value=None, format='DD/MM/YYYY', key='filtro_dt_ini')
    with col_f_dt2:
        filtro_data_fim = st.date_input('Início Previsto (Até):', value=None, format='DD/MM/YYYY', key='filtro_dt_fim')

    filtro_busca_num = st.text_input('🔍 Pesquisar por Nome/Número do Projeto:', placeholder='Digite o número ou parte do projeto...', key='filtro_busca_num_kanban')

    projetos = carregar_projetos()

    if filtro_busca_num.strip():
        projetos = [p for p in projetos if filtro_busca_num.lower() in p[1].lower()]

    if filtro_mod_kanban:
        projetos = [p for p in projetos if p[4] in filtro_mod_kanban]

    if filtro_an_kanban:
        projetos = [p for p in projetos if p[5] in filtro_an_kanban]

    if filtro_data_ini:
        projetos = [p for p in projetos if p[13] and datetime.strptime(p[13], '%Y-%m-%d').date() >= filtro_data_ini]
    if filtro_data_fim:
        projetos = [p for p in projetos if p[13] and datetime.strptime(p[13], '%Y-%m-%d').date() <= filtro_data_fim]

    status_list = ['Em Aberto', 'Em Andamento', 'Pendente', 'Finalizado']
    col1, col2, col3, col4 = st.columns(4)
    colunas_ui = [col1, col2, col3, col4]

    config_status = {
        'Em Aberto': {'fa_icon': 'fa-solid fa-circle-play', 'color': '#38bdf8', 'bg': '#1e293b', 'badge_color': '#38bdf8'},
        'Em Andamento': {'fa_icon': 'fa-solid fa-spinner', 'color': '#facc15', 'bg': '#1e293b', 'badge_color': '#facc15'},
        'Pendente': {'fa_icon': 'fa-solid fa-triangle-exclamation', 'color': '#f87171', 'bg': '#1e293b', 'badge_color': '#f87171'},
        'Finalizado': {'fa_icon': 'fa-solid fa-circle-check', 'color': '#4ade80', 'bg': '#1e293b', 'badge_color': '#4ade80'},
    }

    for idx, status in enumerate(status_list):
        with colunas_ui[idx]:
            projs_status = [p for p in projetos if p[10] == status]
            cfg = config_status[status]
            
            st.markdown(
                f"""
                <div style="display: flex; align-items: center; justify-content: space-between; background: #1e293b; padding: 12px 14px; border-radius: 10px; border-left: 4px solid {cfg['color']}; box-shadow: 0 4px 10px rgba(0,0,0,0.3); margin-bottom: 14px; border: 1px solid #334155;">
                    <span style="font-weight: 700; color: #f8fafc; font-size: 0.95rem;">
                        <i class="{cfg['fa_icon']}" style="color: {cfg['color']}; margin-right: 6px;"></i> {status}
                    </span>
                    <span style="font-size: 0.8rem; font-weight: 800; padding: 2px 10px; border-radius: 12px; background-color: rgba(255,255,255,0.08); color: {cfg['badge_color']};">
                        {len(projs_status)}
                    </span>
                </div>
                """,
                unsafe_allow_html=True,
            )

            for p in projs_status:
                (p_id, p_num, p_pipefy, p_emails_str, p_modulo, p_analista, p_gestor, p_tel_g, p_resp, p_tel_r, 
                 p_sit, p_motivo, p_ba, p_data_prev, p_mod_id, p_analista_id) = p

                pct_chk = calcular_progresso_checklist(p_id)
                horas_prj = calcular_horas_projeto(p_id)
                qtd_notifs_card = len(carregar_historico_notificacoes_projeto(p_id))
                reuniao_prj = carregar_reuniao_projeto(p_id)

                with st.container(border=True):
                    col_card_t, col_card_n = st.columns([0.68, 0.32])
                    with col_card_t:
                        st.markdown(f'**<i class="fa-solid fa-bookmark" style="color: #3b82f6;"></i> {p_num}**', unsafe_allow_html=True)
                    with col_card_n:
                        if st.button(f'🔔 {qtd_notifs_card}', key=f'btn_hist_card_{p_id}'):
                            st.session_state.modal_projeto_id = None
                            st.session_state.modal_historico_id = p_id
                            st.session_state.show_historico_modal = True
                            st.rerun()

                    st.markdown(f"""
                        <div style="font-size: 0.82rem; color: #cbd5e1; margin: 4px 0 8px 0;">
                            <i class="fa-solid fa-cube" style="color: #64748b;"></i> <b>{p_modulo or "N/D"}</b> &bull; 
                            <i class="fa-solid fa-user-tie" style="color: #64748b;"></i> <b>{p_analista or "N/D"}</b>
                        </div>
                    """, unsafe_allow_html=True)

                    st.markdown(f'<span style="color: #38bdf8; font-size: 0.82rem; font-weight: 700;"><i class="fa-solid fa-stopwatch"></i> Tempo de Projeto: {horas_prj}</span>', unsafe_allow_html=True)
                    
                    conn_cc = get_connection()
                    cursor_cc = conn_cc.cursor()
                    cursor_cc.execute("SELECT username, status FROM cronometro_ativo_db WHERE projeto_id = ?", (p_id,))
                    timers_ativos = cursor_cc.fetchall()
                    conn_cc.close()

                    if timers_ativos:
                        st.markdown("<div style='font-size: 0.78rem; color: #facc15; margin-top: 4px;'><b>Cronômetros Ativos:</b></div>", unsafe_allow_html=True)
                        for usr_t, status_t in timers_ativos:
                            icone_st = "🔴 Em andamento" if status_t == 'rodando' else "⏸️ Pausado"
                            st.markdown(f"<div style='font-size: 0.76rem; color: #cbd5e1; margin-left: 6px;'>• Usuário: <b>@{usr_t}</b> ({icone_st})</div>", unsafe_allow_html=True)


                    if reuniao_prj:
                        tit_r, dt_r_str, dt_r_fim_str, url_r = reuniao_prj
                        tempo_restante_txt = calcular_tempo_restante(dt_r_str, dt_r_fim_str)
                        st.caption(f"📅 Reunião: '{tit_r}' ({formatar_data_br(dt_r_str)} - {tempo_restante_txt})")

                    st.progress(pct_chk / 100)
                    st.markdown(f'<span style="color: #4ade80; font-size: 0.8rem; font-weight: 700;"><i class="fa-regular fa-square-check"></i> Checklist: {pct_chk}%</span>', unsafe_allow_html=True)

                    if p_data_prev:
                        dt_prev_obj = datetime.strptime(p_data_prev, '%Y-%m-%d').date()
                        dt_prev_fmt = dt_prev_obj.strftime('%d-%m-%Y')
                        if p_sit == 'Em Aberto':
                            dias_diff = (dt_prev_obj - date.today()).days
                            if dias_diff > 30:
                                st.markdown(f"<span style='color: #4ade80; font-size: 0.8rem; font-weight: 700;'><i class='fa-regular fa-calendar'></i> Início: {dt_prev_fmt} (Faltam {dias_diff}d)</span>", unsafe_allow_html=True)
                            elif 4 <= dias_diff <= 30:
                                st.markdown(f"<span style='color: #facc15; font-size: 0.8rem; font-weight: 700;'><i class='fa-regular fa-calendar'></i> Início: {dt_prev_fmt} (Faltam {dias_diff}d)</span>", unsafe_allow_html=True)
                            elif 0 <= dias_diff <= 3:
                                dias_txt = 'É hoje!' if dias_diff == 0 else f'Faltam {dias_diff}d'
                                st.markdown(f"<span style='color: #f87171; font-size: 0.8rem; font-weight: 700;'><i class='fa-regular fa-calendar-xmark'></i> Início: {dt_prev_fmt} ({dias_txt})</span>", unsafe_allow_html=True)
                            else:
                                st.markdown(f"<span style='color: #f87171; font-size: 0.8rem; font-weight: 700;'><i class='fa-solid fa-triangle-exclamation'></i> Atrasado ({abs(dias_diff)}d)</span>", unsafe_allow_html=True)
                        else:
                            st.caption(f'📅 **Início Prev.:** {dt_prev_fmt}')

                    if p_pipefy:
                        st.markdown(f'<a href="{p_pipefy}" target="_blank" style="font-size: 0.8rem; text-decoration: none; color: #38bdf8; font-weight: 600;"><i class="fa-solid fa-arrow-up-right-from-square"></i> Visualizar Pipefy</a>', unsafe_allow_html=True)
                    if p_ba:
                        st.code(f'BA: {p_ba}', language='text')

                    if p_sit == 'Pendente':
                        st.error(f'⚠️ {p_motivo}')

                    # SELETOR DE MOVIMENTAÇÃO RÁPIDA DE SITUAÇÃO NO CARTÃO
                    novo_st_sel = st.selectbox("Mover para:", status_list, index=status_list.index(p_sit), key=f"quick_move_{p_id}", label_visibility="collapsed")
                    if novo_st_sel != p_sit:
                        chk_items_quick = carregar_checklist(p_id)
                        todos_ok = all(item[2] == 1 for item in chk_items_quick) if chk_items_quick else True

                        if novo_st_sel == 'Finalizado' and not todos_ok:
                            st.error('❌ Checklist precisa estar 100% concluído!')
                        else:
                            conn_m = get_connection()
                            cursor_m = conn_m.cursor()
                            cursor_m.execute("UPDATE projetos SET situacao = ? WHERE id = ?", (novo_st_sel, p_id))
                            conn_m.commit()
                            conn_m.close()
                            registrar_log(f"Projeto '{p_num}' alterou status para '{novo_st_sel}'.", acao='MOVER_STATUS')
                            st.toast(f"Projeto {p_num} movido para {novo_st_sel}!", icon="🚀")
                            st.rerun()

                    if st.button('🔍 Gerenciar Projeto', key=f'btn_modal_{p_id}', use_container_width=True):
                        st.session_state.modal_historico_id = None
                        st.session_state.show_historico_modal = False
                        st.session_state.modal_projeto_id = p_id
                        st.session_state.active_tab_modal = 0
                        st.rerun()

if HAS_SAC:
    if opcao_aba_nome == 'Painel':
        render_painel_kanban()
else:
    with abas[0]:
        render_painel_kanban()

# ==================== CONTROLE RIGOROSO DE ABERTURA DE MODAIS ====================
if st.session_state.get('modal_projeto_id') is not None:
    p_id_modal = st.session_state.modal_projeto_id
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT id FROM projetos WHERE id = ?', (p_id_modal,))
    existe_prj = cursor.fetchone()
    conn.close()
    
    if existe_prj:
        modal_gerenciar_projeto(p_id_modal)
    else:
        st.session_state.modal_projeto_id = None

if st.session_state.get('modal_historico_id') is not None and st.session_state.get('show_historico_modal', False):
    p_id_hist = st.session_state.modal_historico_id
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT id FROM projetos WHERE id = ?', (p_id_hist,))
    existe_prj_hist = cursor.fetchone()
    conn.close()

    if existe_prj_hist:
        modal_historico_notificacoes(p_id_hist)
    else:
        st.session_state.modal_historico_id = None
        st.session_state.show_historico_modal = False

# ==================== ABA 2: AGENDA CORPORATIVA ====================
def render_agenda_corporativa():
    st.markdown('### <i class="fa-solid fa-calendar-days" style="color: #3b82f6;"></i> Agenda de Reuniões & Compromissos', unsafe_allow_html=True)
    st.markdown('Gerencie reuniões, URLs de acesso, compartilhamentos múltiplos, lembretes, edição e pop-ups persistentes.')

    usr_atual = st.session_state.usuario_logado
    usuarios_todos = [u for u in carregar_usuarios_sistema() if u != usr_atual]
    projetos_list_agenda = carregar_projetos()
    proj_dict_agenda = {f"{p[1]} (Módulo: {p[4] or 'N/D'})": p[0] for p in projetos_list_agenda}

    tab_ag1, tab_ag2 = st.tabs(['📅 Meus Compromissos & Compartilhados', '➕ Agendar Nova Reunião'])

    with tab_ag2:
        with st.form('form_nova_reuniao', clear_on_submit=True):
            st.markdown('##### 📝 Detalhes da Reunião')
            titulo_reuniao = st.text_input('Título da Reunião / Assunto :red[*]', placeholder='Ex: Alinhamento de Implantação com Cliente')
            url_reuniao = st.text_input('URL da Reunião (Meet, Teams, Zoom, etc.)', placeholder='https://meet.google.com/abc-defg-hij')
            
            col_d1, col_d2 = st.columns(2)
            with col_d1:
                data_ini_ag = st.date_input('Data de Início', value=datetime.today().date(), format='DD/MM/YYYY')
                hora_ini_ag = st.time_input('Horário de Início', value=datetime.now().time())
            with col_d2:
                data_fim_ag = st.date_input('Data de Término', value=datetime.today().date(), format='DD/MM/YYYY')
                hora_fim_ag = st.time_input('Horário de Término', value=(datetime.now() + timedelta(hours=1)).time())

            col_c1, col_c2 = st.columns(2)
            with col_c1:
                compartilhar_com = st.multiselect('Compartilhar Agenda com Múltiplos Usuários:', options=usuarios_todos, placeholder='Todos', key='agenda_comp_multiselect')
            with col_c2:
                lembrete_min = st.selectbox('Avisar / Lembrete antes de iniciar:', options=[5, 10, 15, 30, 60], index=1, format_func=lambda x: f'{x} minutos antes')

            vinculo_proj = st.selectbox('Vincular a Projeto (Opcional):', options=['Nenhum Projeto'] + list(proj_dict_agenda.keys()))
            enviar_popup_agora = st.checkbox('📢 Enviar Pop-up de Notificação em Tela (para você e todos os marcados)', value=True)

            btn_salvar_reuniao = st.form_submit_button('Salvar e Agendar Reunião', use_container_width=True)

            if btn_salvar_reuniao:
                if not titulo_reuniao.strip():
                    st.error('O título da reunião é obrigatório.')
                else:
                    dt_inicio_full = f"{data_ini_ag.strftime('%Y-%m-%d')} {hora_ini_ag.strftime('%H:%M')}"
                    dt_fim_full = f"{data_fim_ag.strftime('%Y-%m-%d')} {hora_fim_ag.strftime('%H:%M')}"
                    comp_final = ','.join(compartilhar_com) if compartilhar_com else ''
                    p_id_final = proj_dict_agenda.get(vinculo_proj) if vinculo_proj != 'Nenhum Projeto' else None
                    notif_val = 1 if enviar_popup_agora else 0

                    try:
                        conn = get_connection()
                        cursor = conn.cursor()
                        cursor.execute("""
                            INSERT INTO agenda (titulo, url, criador, compartilhado_com, data_inicio, data_fim, lembrete_minutos, projeto_id, notificado_popup)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (titulo_reuniao.strip(), url_reuniao.strip(), usr_atual, comp_final, dt_inicio_full, dt_fim_full, lembrete_min, p_id_final, notif_val))
                        
                        destinatarios_reuniao = list(set([usr_atual] + compartilhar_com))
                        msg_notif = f"📅 Reunião Agendada: '{titulo_reuniao.strip()}' marcada para {formatar_data_br(dt_inicio_full)} por @{usr_atual}."
                        for dest in destinatarios_reuniao:
                            cursor.execute("""
                                INSERT INTO notificacoes (projeto_id, destinatario, remetente, mensagem, data, lida)
                                VALUES (?, ?, ?, ?, ?, 0)
                            """, (p_id_final, dest, usr_atual, msg_notif, datetime.now().strftime('%d-%m-%Y %H:%M')))

                        conn.commit()
                        conn.close()
                        registrar_log(f"Reunião agendada: '{titulo_reuniao.strip()}'", acao='CRIAR_AGENDA')
                        
                        if enviar_popup_agora:
                            st.session_state.popup_mensagens.append({
                                'id': f"nova_reuniao_{datetime.now().timestamp()}",
                                'titulo': "📅 Nova Reunião Agendada",
                                'mensagem': f"'{titulo_reuniao.strip()}' marcada para {formatar_data_br(dt_inicio_full)}"
                            })

                        st.success('Reunião agendada com sucesso! Pop-up e notificações enviadas aos envolvidos.')
                        st.rerun()
                    except Exception as e:
                        st.error(f'Erro ao salvar reunião: {e}')

    with tab_ag1:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, titulo, url, criador, compartilhado_com, data_inicio, data_fim, lembrete_minutos, projeto_id 
            FROM agenda 
            WHERE criador = ? OR compartilhado_com LIKE ? OR compartilhado_com LIKE ? OR compartilhado_com = ?
            ORDER BY data_inicio DESC
        """, (usr_atual, f"%{usr_atual}%", usr_atual, usr_atual))
        compromissos = cursor.fetchall()
        conn.close()

        if compromissos:
            for ev_id, tit, url_r, criador_r, comp_r, dt_i, dt_f, lemb, p_id_r in compromissos:
                tempo_restante_str = calcular_tempo_restante(dt_i, dt_f)
                with st.container(border=True):
                    col_info, col_del = st.columns([0.88, 0.12])
                    with col_info:
                        st.markdown(f"#### 📅 **{tit}** <span style='font-size: 0.85rem; color: #38bdf8; background: rgba(56,189,248,0.1); padding: 2px 8px; border-radius: 6px;'>{tempo_restante_str}</span>", unsafe_allow_html=True)
                        comp_str = f"&bull; **Compartilhado com:** `@{comp_r}`" if comp_r else ""
                        st.markdown(f"**Início:** `{formatar_data_br(dt_i)}` &bull; **Término:** `{formatar_data_br(dt_f)}` &bull; **Criador:** `@{criador_r}` {comp_str}")
                        
                        if url_r:
                            st.markdown(f'<a href="{url_r}" target="_blank" style="font-size: 0.9rem; text-decoration: none; color: #38bdf8; font-weight: 700;"><i class="fa-solid fa-video"></i> Acessar Sala da Reunião (URL)</a>', unsafe_allow_html=True)
                        
                        if p_id_r:
                            conn = get_connection()
                            cursor = conn.cursor()
                            cursor.execute('SELECT num_projeto FROM projetos WHERE id = ?', (p_id_r,))
                            r_p = cursor.fetchone()
                            conn.close()
                            if r_p:
                                st.caption(f"🔗 Vinculado ao Projeto: **{r_p[0]}**")
                    with col_del:
                        if criador_r == usr_atual or st.session_state.perfil_logado == 'Administrador':
                            if st.button('🗑️', key=f'del_ag_{ev_id}', help='Excluir agendamento', use_container_width=True):
                                conn = get_connection()
                                cursor = conn.cursor()
                                cursor.execute('DELETE FROM agenda WHERE id = ?', (ev_id,))
                                conn.commit()
                                conn.close()
                                registrar_log(f"Reunião ID {ev_id} excluída.", acao='EXCLUIR_AGENDA')
                                st.success('Excluído!')
                                st.rerun()

                    if criador_r == usr_atual or st.session_state.perfil_logado == 'Administrador':
                        with st.expander(f"✏️ Editar Reunião: {tit}"):
                            with st.form(f"form_edit_reuniao_{ev_id}"):
                                edit_tit = st.text_input('Título', value=tit, key=f'edit_tit_{ev_id}')
                                edit_url = st.text_input('URL da Reunião', value=url_r or '', key=f'edit_url_{ev_id}')
                                
                                try:
                                    dt_ini_obj = datetime.strptime(dt_i, '%Y-%m-%d %H:%M')
                                    dt_fim_obj = datetime.strptime(dt_f, '%Y-%m-%d %H:%M')
                                except Exception:
                                    dt_ini_obj = datetime.now()
                                    dt_fim_obj = datetime.now() + timedelta(hours=1)

                                col_ed1, col_ed2 = st.columns(2)
                                with col_ed1:
                                    ed_d_ini = st.date_input('Data Início', value=dt_ini_obj.date(), key=f'ed_d_ini_{ev_id}', format='DD/MM/YYYY')
                                    ed_h_ini = st.time_input('Hora Início', value=dt_ini_obj.time(), key=f'ed_h_ini_{ev_id}')
                                with col_ed2:
                                    ed_d_fim = st.date_input('Data Término', value=dt_fim_obj.date(), key=f'ed_d_fim_{ev_id}', format='DD/MM/YYYY')
                                    ed_h_fim = st.time_input('Hora Término', value=dt_fim_obj.time(), key=f'ed_h_fim_{ev_id}')

                                ed_lemb = st.selectbox('Lembrete (min)', options=[5, 10, 15, 30, 60], index=[5, 10, 15, 30, 60].index(lemb) if lemb in [5, 10, 15, 30, 60] else 1, key=f'ed_lemb_{ev_id}')

                                comp_atuais_list = [c.strip() for c in comp_r.split(',') if c.strip()] if comp_r else []
                                ed_compartilhar = st.multiselect('Compartilhar / Notificar Usuários:', options=usuarios_todos, default=[u for u in comp_atuais_list if u in usuarios_todos], placeholder='Todos', key=f'ed_comp_{ev_id}')

                                proj_opts_keys = ['Nenhum Projeto'] + list(proj_dict_agenda.keys())
                                default_proj_idx = 0
                                if p_id_r:
                                    for p_k, p_v in proj_dict_agenda.items():
                                        if p_v == p_id_r:
                                            default_proj_idx = proj_opts_keys.index(p_k)
                                            break
                                ed_proj = st.selectbox('Vincular a Projeto', options=proj_opts_keys, index=default_proj_idx, key=f'ed_proj_{ev_id}')

                                btn_save_ed_ag = st.form_submit_button('Salvar alterações da reunião', use_container_width=True)
                                if btn_save_ed_ag:
                                    novo_dt_ini_str = f"{ed_d_ini.strftime('%Y-%m-%d')} {ed_h_ini.strftime('%H:%M')}"
                                    novo_dt_fim_str = f"{ed_d_fim.strftime('%Y-%m-%d')} {ed_h_fim.strftime('%H:%M')}"
                                    novo_pid_val = proj_dict_agenda.get(ed_proj) if ed_proj != 'Nenhum Projeto' else None
                                    comp_edit_final = ','.join(ed_compartilhar) if ed_compartilhar else ''

                                    conn_e = get_connection()
                                    cursor_e = conn_e.cursor()
                                    cursor_e.execute("""
                                        UPDATE agenda 
                                        SET titulo = ?, url = ?, compartilhado_com = ?, data_inicio = ?, data_fim = ?, lembrete_minutos = ?, projeto_id = ?, notificado_popup = 0
                                        WHERE id = ?
                                    """, (edit_tit.strip(), edit_url.strip(), comp_edit_final, novo_dt_ini_str, novo_dt_fim_str, ed_lemb, novo_pid_val, ev_id))
                                    
                                    envolvidos = list(set([criador_r] + ed_compartilhar))
                                    msg_edit = f"✏️ Reunião Alterada: '{edit_tit.strip()}' ajustada para {formatar_data_br(novo_dt_ini_str)} por @{usr_atual}."
                                    for dest in envolvidos:
                                        cursor_e.execute("""
                                            INSERT INTO notificacoes (projeto_id, destinatario, remetente, mensagem, data, lida)
                                            VALUES (?, ?, ?, ?, ?, 0)
                                        """, (novo_pid_val, dest, usr_atual, msg_edit, datetime.now().strftime('%d-%m-%Y %H:%M')))

                                    conn_e.commit()
                                    conn_e.close()
                                    registrar_log(f"Reunião ID {ev_id} editada com notificação aos envolvidos.", acao='EDITAR_AGENDA')
                                    st.success('Alterações efetuadas com sucesso! Notificações enviadas aos envolvidos.')
                                    st.rerun()
        else:
            st.info('Nenhuma reunião agendada na sua agenda.')

if HAS_SAC:
    if opcao_aba_nome == 'Agenda':
        render_agenda_corporativa()
else:
    with abas[1]:
        render_agenda_corporativa()

# ==================== ABA: RELATÓRIO DE HORAS & CRONÔMETROS ====================
def render_relatorio_horas_cronometros():
    st.markdown('### <i class="fa-solid fa-stopwatch" style="color: #3b82f6;"></i> Relatório de Horas & Cronômetros por Projeto', unsafe_allow_html=True)
    st.markdown('Acompanhe o tempo investido por cada analista e visualize todos os profissionais que participaram de cada implantação.')

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT tp.id, p.num_projeto, tp.usuario, tp.data_registro, tp.minutos_gastos, m.nome as modulo
        FROM tempo_projetos tp
        JOIN projetos p ON tp.projeto_id = p.id
        LEFT JOIN modulos m ON p.modulo_id = m.id
        ORDER BY tp.id DESC
    """)
    horas_registradas = cursor.fetchall()
    conn.close()

    if not horas_registradas:
        st.info('Nenhum registro de horas por cronômetro encontrado até o momento.')
        return

    dados_tabela = []
    for r_id, p_num, usr, dt_reg, mins, mod_nome in horas_registradas:
        hrs = mins // 60
        m_rest = mins % 60
        tempo_fmt = f"{hrs}h {m_rest}m" if hrs > 0 else f"{m_rest}m"
        
        data_formatada = dt_reg
        try:
            if dt_reg:
                data_formatada = datetime.strptime(dt_reg.split()[0], '%Y-%m-%d').strftime('%d/%m/%Y')
        except Exception:
            pass

        dados_tabela.append({
            'ID Registro': r_id,
            'Projeto': p_num,
            'Módulo': mod_nome or 'N/D',
            'Analista / Usuário': f"@{usr}",
            'Data': data_formatada,
            'Minutos': mins,
            'Tempo Dedicado': tempo_fmt
        })

    df_horas = pd.DataFrame(dados_tabela)

    col_h1, col_h2 = st.columns(2)
    with col_h1:
        filtro_proj_hr = st.multiselect('Filtrar por Projeto:', options=df_horas['Projeto'].unique(), placeholder='Todos', key='hr_proj_filter')
    with col_h2:
        filtro_usr_hr = st.multiselect('Filtrar por Analista / Usuário:', options=df_horas['Analista / Usuário'].unique(), placeholder='Todos', key='hr_usr_filter')

    if filtro_proj_hr:
        df_horas = df_horas[df_horas['Projeto'].isin(filtro_proj_hr)]
    if filtro_usr_hr:
        df_horas = df_horas[df_horas['Analista / Usuário'].isin(filtro_usr_hr)]

    st.markdown('---')
    st.dataframe(df_horas[['ID Registro', 'Projeto', 'Módulo', 'Analista / Usuário', 'Data', 'Tempo Dedicado']], use_container_width=True, hide_index=True)

    if st.session_state.perfil_logado == 'Administrador':
        st.markdown('---')
        st.markdown('##### ✏️ Gerenciamento e Ajuste de Horas (Painel Administrativo)')
        st.markdown('Caso tenha ocorrido algum lançamento equivocado de tempo por cronômetro, o Administrador pode ajustá-lo ou excluí-lo abaixo.')

        with st.form('form_admin_ajuste_horas'):
            id_para_ajustar = st.selectbox('Selecione o ID do Registro de Horas:', options=df_horas['ID Registro'].tolist(), format_func=lambda x: f"Registro ID #{x} - Projeto: {df_horas[df_horas['ID Registro'] == x]['Projeto'].values[0]} (@{df_horas[df_horas['ID Registro'] == x]['Analista / Usuário'].values[0]})")
            
            reg_atual_row = df_horas[df_horas['ID Registro'] == id_para_ajustar].iloc[0]
            novo_minuto_val = st.number_input('Novo valor em Minutos:', min_value=1, value=int(reg_atual_row['Minutos']), step=5)
            
            col_a_btn1, col_a_btn2 = st.columns(2)
            with col_a_btn1:
                btn_salvar_ajuste = st.form_submit_button('💾 Atualizar Minutos do Registro', use_container_width=True)
            with col_a_btn2:
                btn_excluir_ajuste = st.form_submit_button('🗑️ Excluir Registro de Horas', use_container_width=True)

            if btn_salvar_ajuste:
                conn_ed = get_connection()
                cursor_ed = conn_ed.cursor()
                cursor_ed.execute("UPDATE tempo_projetos SET minutos_gastos = ? WHERE id = ?", (novo_minuto_val, id_para_ajustar))
                conn_ed.commit()
                conn_ed.close()
                registrar_log(f"Administrador ajustou o registro de horas ID #{id_para_ajustar} para {novo_minuto_val} minutos.", acao='AJUSTE_HORAS_ADMIN')
                st.success(f"Registro ID #{id_para_ajustar} atualizado com sucesso!")
                st.rerun()

            if btn_excluir_ajuste:
                conn_del = get_connection()
                cursor_del = conn_del.cursor()
                cursor_del.execute("DELETE FROM tempo_projetos WHERE id = ?", (id_para_ajustar,))
                conn_del.commit()
                conn_del.close()
                registrar_log(f"Administrador excluiu o registro de horas ID #{id_para_ajustar}.", acao='EXCLUIR_HORAS_ADMIN')
                st.success(f"Registro ID #{id_para_ajustar} excluído com sucesso!")
                st.rerun()

if HAS_SAC:
    if opcao_aba_nome == 'Relatório de Horas & Cronômetros':
        render_relatorio_horas_cronometros()
else:
    pass

# ==================== ABA: RELATÓRIOS AVANÇADOS ====================
def render_relatorios():
    st.markdown('### <i class="fa-solid fa-file-invoice-dollar" style="color: #3b82f6;"></i> Módulo de Relatórios de Implantação', unsafe_allow_html=True)

    projetos_todos = carregar_projetos()

    col_f1, col_f2, col_f3 = st.columns(3)
    modulos_opc = ['Todos'] + [m[1] for m in carregar_modulos()]
    analistas_opc = ['Todos'] + [a[1] for a in carregar_analistas()]
    status_opc = ['Todos', 'Em Aberto', 'Em Andamento', 'Pendente', 'Finalizado']

    with col_f1:
        filtro_mod = st.selectbox('Módulo', modulos_opc, key='rel_mod_sel')
    with col_f2:
        filtro_an = st.selectbox('Analista', analistas_opc, key='rel_an_sel')
    with col_f3:
        filtro_st = st.selectbox('Situação', status_opc, key='rel_st_sel')

    projetos_filtrados = []
    projetos_filtrados_raw = []
    for p in projetos_todos:
        (p_id, p_num, p_pipefy, p_emails_str, p_modulo, p_analista, p_gestor, p_tel_g, p_resp, p_tel_r, 
         p_sit, p_motivo, p_ba, p_data_prev, p_mod_id, p_analista_id) = p

        if filtro_mod != 'Todos' and p_modulo != filtro_mod:
            continue
        if filtro_an != 'Todos' and p_analista != filtro_an:
            continue
        if filtro_st != 'Todos' and p_sit != filtro_st:
            continue

        projetos_filtrados_raw.append(p)
        pct_chk = calcular_progresso_checklist(p_id)

        data_formatada = '-'
        if p_data_prev:
            try:
                data_formatada = datetime.strptime(p_data_prev, '%Y-%m-%d').strftime('%d-%m-%Y')
            except Exception:
                data_formatada = p_data_prev

        projetos_filtrados.append({
            'Nº Projeto': p_num,
            'Módulo': p_modulo or 'N/D',
            'Analista': p_analista or 'N/D',
            'Situação': p_sit,
            'Checklist %': f'{pct_chk}%',
            'Data Prevista': data_formatada,
            'BA': p_ba or '-',
            'E-mails': p_emails_str or '-',
            'Gestor Contrato': p_gestor or '-',
            'Responsável': p_resp or '-',
            'Link Pipefy': p_pipefy or '-',
        })

    st.markdown('---')

    todas_colunas_disponiveis = [
        'Nº Projeto', 'Módulo', 'Analista', 'Situação', 'Checklist %', 
        'Data Prevista', 'BA', 'E-mails', 'Gestor Contrato', 'Responsável', 'Link Pipefy'
    ]

    colunas_selecionadas = st.multiselect(
        '👁️ Escolher Colunas Visíveis (Respeitado na Impressão e Exportação):',
        options=todas_colunas_disponiveis,
        default=['Nº Projeto', 'Módulo', 'Analista', 'Situação', 'Checklist %', 'Data Prevista', 'BA', 'E-mails'],
        placeholder='Todos',
        key='multiselect_colunas_relatorio_principal',
    )

    st.metric('Total Encontrado', len(projetos_filtrados))

    if projetos_filtrados:
        df_rel = pd.DataFrame(projetos_filtrados)
        df_exibicao = df_rel[colunas_selecionadas] if colunas_selecionadas else df_rel

        st.dataframe(df_exibicao, use_container_width=True)

        col_down1, col_down2, col_down3, col_down4 = st.columns(4)
        with col_down1:
            csv_data = df_exibicao.to_csv(index=False).encode('utf-8')
            st.download_button(
                '📥 Baixar CSV',
                csv_data,
                f'relatorio_{datetime.now().strftime("%Y%m%d")}.csv',
                'text/csv',
                use_container_width=True,
                key='btn_csv_download'
            )

        with col_down2:
            if HAS_REPORTLAB:
                pdf_data = gerar_pdf_relatorio(df_exibicao, colunas_selecionadas)
                st.download_button(
                    '📄 Exportar PDF Direto',
                    data=pdf_data,
                    file_name=f'relatorio_implantação_{datetime.now().strftime("%Y%m%d_%H%M")}.pdf',
                    mime='application/pdf',
                    use_container_width=True,
                    key='btn_pdf_download'
                )
            else:
                st.caption("Instale 'reportlab' para PDF.")

        with col_down3:
            if HAS_REPORTLAB and projetos_filtrados_raw:
                pdf_chk_filtrados = gerar_pdf_checklist_filtrados(projetos_filtrados_raw)
                st.download_button(
                    '📑 Baixar Checklist (Filtro)',
                    data=pdf_chk_filtrados,
                    file_name=f'checklists_filtrados_{datetime.now().strftime("%Y%m%d_%H%M")}.pdf',
                    mime='application/pdf',
                    use_container_width=True,
                    key='btn_pdf_chk_filtrados'
                )

        with col_down4:
            html_tabela = f"""
            <html>
            <head>
                <meta charset="utf-8">
                <title>Relatório de Implantações</title>
                <style>
                    body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 25px; color: #1e293b; }}
                    h2 {{ color: #0f172a; margin-bottom: 5px; font-weight: 700; }}
                    p {{ color: #64748b; font-size: 13px; margin-bottom: 20px; }}
                    table {{ width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 12px; }}
                    th, td {{ border: 1px solid #cbd5e1; padding: 10px 12px; text-align: left; }}
                    th {{ background-color: #0f172a; color: white; font-weight: 600; }}
                    tr:nth-child(even) {{ background-color: #f8fafc; }}
                </style>
            </head>
            <body>
                <h2>Relatório de Implantações</h2>
                <p>Gerado em: {datetime.now().strftime("%d-%m-%Y %H:%M")} | Usuário: {st.session_state.usuario_logado}</p>
                <table>
                    <thead>
                        <tr>
            """
            for col in colunas_selecionadas:
                html_tabela += f'<th>{col}</th>'

            html_tabela += """
                        </tr>
                    </thead>
                    <tbody>
            """

            for _, row in df_exibicao.iterrows():
                html_tabela += '<tr>'
                for col in colunas_selecionadas:
                    html_tabela += f'<td>{row[col]}</td>'
                html_tabela += '</tr>'

            html_tabela += """
                    </tbody>
                </table>
            </body>
            </html>
            """

            html_json = json.dumps(html_tabela)

            components.html(
                f"""
                <style>
                    .st-button-replica {{
                        display: inline-flex;
                        align-items: center;
                        justify-content: center;
                        background-color: #ffffff;
                        color: #0f172a;
                        padding: 0.45rem 0.85rem;
                        border: 1px solid #cbd5e1;
                        border-radius: 0.5rem;
                        font-weight: 600;
                        font-size: 14px;
                        font-family: sans-serif;
                        cursor: pointer;
                        width: 100%;
                        box-sizing: border-box;
                        box-shadow: 0 1px 2px rgba(0,0,0,0.05);
                        transition: all 0.2s;
                    }}
                    .st-button-replica:hover {{
                        background-color: #f1f5f9;
                        border-color: #94a3b8;
                    }}
                </style>
                <button onclick="openPrintWindow()" class="st-button-replica">
                    🖨️ Imprimir
                </button>
                <script>
                    function openPrintWindow() {{
                        var content = {html_json};
                        var win = window.open('', '_blank');
                        if (win) {{
                            win.document.open();
                            win.document.write(content);
                            win.document.close();
                            win.focus();
                            setTimeout(function() {{ win.print(); }}, 250);
                        }} else {{
                            alert('Por favor, permita pop-ups para este site para usar a impressão.');
                        }}
                    }}
                </script>
            """,
                height=45,
            )

if HAS_SAC:
    if opcao_aba_nome == 'Relatórios Avançados':
        render_relatorios()

# ==================== ABA: DASHBOARD ANALYTICS ====================
def render_dashboard():
    st.markdown('### <i class="fa-solid fa-chart-line" style="color: #3b82f6;"></i> Dashboard Analytics & Indicadores Executivos', unsafe_allow_html=True)

    projetos_all = carregar_projetos()

    if projetos_all:
        col_d_f1, col_d_f2 = st.columns([2, 2])
        with col_d_f1:
            dash_mod_filtro = st.multiselect('Módulos:', options=[m[1] for m in carregar_modulos()], placeholder='Todos', key='dash_filter_mod')
        with col_d_f2:
            dash_an_filtro = st.multiselect('Analistas:', options=[a[1] for a in carregar_analistas()], placeholder='Todos', key='dash_filter_an')

        projetos_dash = projetos_all
        if dash_mod_filtro:
            projetos_dash = [p for p in projetos_dash if p[4] in dash_mod_filtro]
        if dash_an_filtro:
            projetos_dash = [p for p in projetos_dash if p[5] in dash_an_filtro]

        total_dash = len(projetos_dash)

        if total_dash > 0:
            fin_p = len([p for p in projetos_dash if p[10] == 'Finalizado'])
            and_p = len([p for p in projetos_dash if p[10] == 'Em Andamento'])
            pend_p = len([p for p in projetos_dash if p[10] == 'Pendente'])
            ab_p = len([p for p in projetos_dash if p[10] == 'Em Aberto'])

            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric('Total Projetos', total_dash)
            c2.metric('🟢 Finalizados', fin_p, delta=f'{(fin_p/total_dash)*100:.1f}%')
            c3.metric('🟡 Em Andamento', and_p)
            c4.metric('🔴 Pendentes', pend_p)
            c5.metric('🔵 Em Aberto', ab_p)

            st.markdown('---')

            df_dash = pd.DataFrame(
                projetos_dash,
                columns=['ID', 'Num', 'Pipefy', 'Emails', 'Modulo', 'Analista', 'Gestor', 'TelG', 'Resp', 'TelR', 'Situacao', 'Motivo', 'BA', 'DataPrev', 'ModID', 'AnID'],
            )

            col_g1, col_g2 = st.columns(2)

            with col_g1:
                col_g1_head, col_g1_sel = st.columns([0.6, 0.4])
                with col_g1_head:
                    st.markdown('##### 📈 Distribuição por Situação')
                with col_g1_sel:
                    tipo_g1 = st.selectbox('Tipo de Gráfico:', ['Pizza 🍕', 'Barras Verticais 📊', 'Linhas 📈', 'Funil '], key='g1_type_sel')

                status_counts = df_dash['Situacao'].value_counts().reset_index(name='Quantidade').rename(columns={'index': 'Situacao'})

                if 'Pizza' in tipo_g1:
                    fig_status = px.pie(status_counts, values='Quantidade', names='Situacao', color='Situacao', hole=0.45, color_discrete_map=PALETA_CORES_STATUS)
                elif 'Barras' in tipo_g1:
                    fig_status = px.bar(status_counts, x='Situacao', y='Quantidade', color='Situacao', color_discrete_map=PALETA_CORES_STATUS, text='Quantidade')
                elif 'Linhas' in tipo_g1:
                    fig_status = px.line(status_counts, x='Situacao', y='Quantidade', markers=True, color_discrete_sequence=['#3b82f6'])
                else:
                    fig_status = px.funnel(status_counts, x='Quantidade', y='Situacao', color='Situacao', color_discrete_map=PALETA_CORES_STATUS)

                fig_status.update_layout(margin=dict(t=20, b=20, l=20, r=20), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font=dict(color='#f8fafc'))
                st.plotly_chart(fig_status, use_container_width=True)

            with col_g2:
                col_g2_head, col_g2_sel = st.columns([0.6, 0.4])
                with col_g2_head:
                    st.markdown('##### 📦 Volume por Módulo')
                with col_g2_sel:
                    tipo_g2 = st.selectbox('Tipo de Gráfico:', ['Barras Verticais 📊', 'Pizza 🍕', 'Linhas 📈'], key='g2_type_sel')

                mod_df = df_dash['Modulo'].value_counts().reset_index(name='Quantidade').rename(columns={'index': 'Modulo'})

                if 'Barras' in tipo_g2:
                    fig_bar_mod = px.bar(mod_df, x='Modulo', y='Quantidade', color_discrete_sequence=['#3b82f6'], text='Quantidade')
                elif 'Pizza' in tipo_g2:
                    fig_bar_mod = px.pie(mod_df, values='Quantidade', names='Modulo', hole=0.4)
                else:
                    fig_bar_mod = px.line(mod_df, x='Modulo', y='Quantidade', markers=True)

                fig_bar_mod.update_layout(xaxis=dict(tickangle=0, title=None), yaxis=dict(title=None), margin=dict(t=20, b=20, l=20, r=20), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font=dict(color='#f8fafc'))
                st.plotly_chart(fig_bar_mod, use_container_width=True)

            st.markdown('---')

            col_g3, col_g4 = st.columns(2)
            with col_g3:
                st.markdown('##### 👨‍💻 Carga de Trabalho por Analista')
                analista_sit = df_dash.groupby(['Analista', 'Situacao']).size().reset_index(name='Quantidade')

                fig_an = px.bar(analista_sit, x='Analista', y='Quantidade', color='Situacao', barmode='stack', color_discrete_map=PALETA_CORES_STATUS, text='Quantidade')
                fig_an.update_layout(xaxis=dict(tickangle=0, title=None), yaxis=dict(title=None), legend=dict(orientation='h', y=1.15, title=None), margin=dict(t=20, b=20, l=20, r=20), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font=dict(color='#f8fafc'))
                st.plotly_chart(fig_an, use_container_width=True)

            with col_g4:
                st.markdown('##### 🧩 Status por Módulo')
                mod_sit = df_dash.groupby(['Modulo', 'Situacao']).size().reset_index(name='Quantidade')

                fig_mod_sit = px.bar(mod_sit, x='Modulo', y='Quantidade', color='Situacao', barmode='group', color_discrete_map=PALETA_CORES_STATUS, text='Quantidade')
                fig_mod_sit.update_layout(xaxis=dict(tickangle=0, title=None), yaxis=dict(title=None), legend=dict(orientation='h', y=1.15, title=None), margin=dict(t=20, b=20, l=20, r=20), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font=dict(color='#f8fafc'))
                st.plotly_chart(fig_mod_sit, use_container_width=True)

        else:
            st.info('Nenhum dado encontrado para os filtros selecionados.')
    else:
        st.info('Cadastre projetos para visualizar o Dashboard.')

if HAS_SAC:
    if opcao_aba_nome == 'Dashboard Analytics':
        render_dashboard()

# ==================== ABA: AUDITORIA DE LOGS ====================
def render_auditoria_completa():
    st.markdown('### <i class="fa-solid fa-shield-halved" style="color: #3b82f6;"></i> Módulo de Auditoria e Eventos do Sistema', unsafe_allow_html=True)
    st.markdown('Visualize abaixo todas as operações realizadas pelos usuários.')

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, usuario, acao, detalhes, data_hora 
        FROM logs_auditoria 
        ORDER BY id DESC
    """)
    logs_raw = cursor.fetchall()
    conn.close()

    if not logs_raw:
        st.info('Nenhum log de auditoria registrado até o momento.')
        return

    df_logs = pd.DataFrame(logs_raw, columns=['ID', 'Usuário', 'Ação', 'Detalhes', 'Data/Hora'])

    col_a1, col_a2 = st.columns(2)
    with col_a1:
        usr_filter = st.multiselect('Filtrar por Usuário:', options=df_logs['Usuário'].unique(), placeholder='Todos', key='audit_page_usr_filter')
    with col_a2:
        acao_filter = st.multiselect('Filtrar por Ação:', options=df_logs['Ação'].unique(), placeholder='Todos', key='audit_page_acao_filter')

    if usr_filter:
        df_logs = df_logs[df_logs['Usuário'].isin(usr_filter)]
    if acao_filter:
        df_logs = df_logs[df_logs['Ação'].isin(acao_filter)]

    st.markdown('---')
    st.metric('Total de Registros de Auditoria', len(df_logs))
    st.dataframe(df_logs, use_container_width=True)

    st.download_button(
        '📥 Baixar Auditoria em CSV',
        df_logs.to_csv(index=False).encode('utf-8'),
        f'auditoria_logs_{datetime.now().strftime("%Y%m%d_%H%M")}.csv',
        'text/csv',
        use_container_width=True,
        key='btn_audit_csv'
    )

if HAS_SAC:
    if opcao_aba_nome == 'Auditoria de Logs':
        render_auditoria_completa()

# ==================== ABA: ACESSO AO DB (TERMINAL SQL & ANALYTICS) ====================
def render_terminal_db():
    st.markdown('### <i class="fa-solid fa-terminal" style="color: #3b82f6;"></i> Terminal de Acesso ao DB & Telemetria do Servidor', unsafe_allow_html=True)
    st.markdown('Execute comandos SQL e acompanhe indicadores analíticos e capacidade de armazenamento em tempo real.')

    st.markdown('#### 📊 Métricas de Servidor e Armazenamento Local')
    
    total_b, used_b, free_b = shutil.disk_usage("/")
    total_gb = total_b / (1024**3)
    used_gb = used_b / (1024**3)
    free_gb = free_b / (1024**3)
    pct_used = (used_b / total_b) * 100

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COALESCE(SUM(LENGTH(dados_arquivo)), 0) FROM anexos;")
    bytes_anexos = cursor.fetchone()[0]
    mb_anexos = bytes_anexos / (1024 * 1024)

    cursor.execute("SELECT COUNT(*) FROM anexos;")
    qtd_anexos = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table';")
    qtd_tabelas = cursor.fetchone()[0]
    conn.close()

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Espaço em Disco Usado", f"{used_gb:.1f} GB / {total_gb:.1f} GB", delta=f"{pct_used:.1f}% Usado")
    m2.metric("Espaço Livre em Disco", f"{free_gb:.1f} GB")
    m3.metric("Volume de Anexos no Banco", f"{mb_anexos:.2f} MB", delta=f"{qtd_anexos} arquivos")
    m4.metric("Tabelas no SQLite", f"{qtd_tabelas} tabelas")

    st.markdown("---")

    col_top_db1, col_top_db2 = st.columns([0.5, 0.5])
    with col_top_db1:
        with st.popover("📊 Diagrama ER de Relacionamento das Tabelas", use_container_width=True):
            st.markdown("### Diagrama Relacional Gráfico (ERD)")
            st.markdown("""
            ```mermaid
            erDiagram
                usuarios ||--o{ notificacoes : envia
                usuarios ||--|| permissoes_usuarios : possui
                usuarios }o--|| analistas : vinculo
                modulos ||--o{ projetos : categoriza
                analistas ||--o{ projetos : responsavel
                projetos ||--o{ checklists : contem
                projetos ||--o{ anexos : possui
                projetos ||--o{ tempo_projetos : registra
                projetos ||--o{ comentarios : recebe
                projetos ||--o{ agenda : agendado
                checklists ||--o{ anexos : vincula
            ```
            """, unsafe_allow_html=True)

    with col_top_db2:
        with st.popover("📖 Dicionário de Dados do Sistema", use_container_width=True):
            st.markdown("### Dicionário de Tabelas e Campos")
            tab_escolhida = st.selectbox("Selecione a Tabela:", ['projetos', 'checklists', 'anexos', 'tempo_projetos', 'usuarios', 'agenda', 'notificacoes', 'logs_auditoria', 'comentarios', 'modulos', 'analistas'])
            
            conn_d = get_connection()
            cursor_d = conn_d.cursor()
            cursor_d.execute(f"PRAGMA table_info({tab_escolhida});")
            cols_info = cursor_d.fetchall()
            conn_d.close()
            
            df_cols = pd.DataFrame(cols_info, columns=['ID', 'Campo', 'Tipo', 'Não Nulo', 'Valor Padrão', 'Chave Primária'])
            st.dataframe(df_cols[['Campo', 'Tipo', 'Não Nulo', 'Valor Padrão', 'Chave Primária']], use_container_width=True, hide_index=True)

    sql_query = st.text_area('Digite a consulta SQL:', value="SELECT * FROM projetos;", height=100, key='sql_terminal_input')

    if st.button('Executar Comando SQL', use_container_width=True, key='btn_exec_sql'):
        if sql_query.strip():
            try:
                conn = get_connection()
                cursor = conn.cursor()
                cursor.execute(sql_query)
                
                query_upper = sql_query.strip().upper()
                if query_upper.startswith('SELECT') or query_upper.startswith('PRAGMA') or query_upper.startswith('EXPLAIN'):
                    res_rows = cursor.fetchall()
                    col_names = [description[0] for description in cursor.description] if cursor.description else []
                    conn.close()

                    if res_rows and col_names:
                        df_sql = pd.DataFrame(res_rows, columns=col_names)
                        st.success(f'Consulta executada com sucesso! {len(df_sql)} registros retornados.')
                        st.dataframe(df_sql, use_container_width=True)
                    else:
                        st.info('Consulta executada com sucesso. Nenhum registro retornado.')
                else:
                    conn.commit()
                    conn.close()
                    registrar_log(f"Comando SQL executado no Terminal DB: {sql_query[:100]}", acao='SQL_TERMINAL')
                    st.success('Comando executado e alterações salvas no banco com sucesso!')
            except Exception as e:
                st.error(f'❌ Erro ao executar comando SQL: {e}')
        else:
            st.warning('Digite um comando SQL válido.')

if HAS_SAC:
    if opcao_aba_nome == 'Acesso ao DB (Terminal)':
        render_terminal_db()

# ==================== RENDERIZAR POP-UPS PROFISSIONAIS ====================
if st.session_state.popup_mensagens:
    st.markdown("""
        <style>
        .windows-toast-container {
            position: fixed;
            bottom: 24px;
            right: 24px;
            z-index: 999999;
            display: flex;
            flex-direction: column;
            gap: 12px;
            max-width: 360px;
            width: 100%;
            pointer-events: none;
        }
        .windows-toast-card {
            background: rgba(30, 41, 59, 0.95);
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            color: #f8fafc;
            border: 1px solid rgba(59, 130, 246, 0.4);
            border-left: 5px solid #3b82f6;
            padding: 16px 18px;
            border-radius: 12px;
            box-shadow: 0 12px 36px rgba(0, 0, 0, 0.6), 0 0 0 1px rgba(255, 255, 255, 0.05) inset;
            pointer-events: auto;
            animation: slideInRight 0.3s cubic-bezier(0.16, 1, 0.3, 1) forwards;
            position: relative;
        }
        @keyframes slideInRight {
            from {
                transform: translateX(110%);
                opacity: 0;
            }
            to {
                transform: translateX(0);
                opacity: 1;
            }
        }
        .toast-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 6px;
        }
        .toast-title {
            font-weight: 700;
            color: #38bdf8;
            font-size: 0.92rem;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .toast-body {
            font-size: 0.85rem;
            color: #cbd5e1;
            line-height: 1.4;
            margin-bottom: 12px;
        }
        </style>
        <div class="windows-toast-container">
    """, unsafe_allow_html=True)
    
    for p_idx, pop in enumerate(list(st.session_state.popup_mensagens)):
        with st.container():
            st.markdown(f"""
                <div class="windows-toast-card">
                    <div class="toast-header">
                        <div class="toast-title">
                            <i class="fa-solid fa-circle-exclamation" style="color: #38bdf8;"></i> {pop['titulo']}
                        </div>
                    </div>
                    <div class="toast-body">
                        {pop['mensagem']}
                    </div>
                </div>
            """, unsafe_allow_html=True)
            if st.button("✕ Fechar [X]", key=f"dismiss_popup_{p_idx}_{pop.get('id', p_idx)}", use_container_width=True):
                pop_id_str = str(pop.get('id', ''))
                if pop_id_str.startswith('notif_db_'):
                    try:
                        db_n_id = int(pop_id_str.replace('notif_db_', ''))
                        conn_toast = sqlite3.connect(DB_NAME)
                        cursor_toast = conn_toast.cursor()
                        cursor_toast.execute("UPDATE notificacoes SET lida = 1 WHERE id = ?", (db_n_id,))
                        conn_toast.commit()
                        conn_toast.close()
                    except Exception:
                        pass
                st.session_state.popup_mensagens.pop(p_idx)
                st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)

# ==================== RODAPÉ ENTERPRISE FULL-WIDTH ====================
st.markdown("""
    <div class="app-footer">
        <div class="footer-inner">
            <div>
                <i class="fa-solid fa-bolt" style="color: #38bdf8; margin-right: 6px;"></i> <b>Gestão de Implantações</b> &bull; Todos os direitos reservados &copy; 2026.
            </div>
            <div class="footer-links">
                <a href="#"><i class="fa-solid fa-shield"></i> Segurança</a>
                <span>|</span>
                <a href="#"><i class="fa-solid fa-code"></i> API Status</a>
                <span>|</span>
                <a href="#"><i class="fa-solid fa-headset"></i> Suporte Técnico</a>
            </div>
        </div>
    </div>
""", unsafe_allow_html=True)