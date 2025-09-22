import gspread
import asyncio
import threading
import os
import json
import requests
from flask import Flask, request
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Bot, Update
from oauth2client.service_account import ServiceAccountCredentials
import traceback

TOKEN = os.environ.get('TOKEN')
CREDS_FILE = "creds.json"
SHEET_NAME = os.environ['SHEET_NAME']
CHAT_ID = "5592767305"

with open(CREDS_FILE, 'w') as f:
    f.write(os.environ['CREDS_FILE'])

loop = asyncio.new_event_loop()
threading.Thread(target=loop.run_forever, daemon=True).start()

app = Flask(__name__)
bot = Bot(token=TOKEN)

RENDER_URL = os.environ['RENDER_URL']
WEBHOOK_URL = f"{RENDER_URL}/webhook/{TOKEN}"

def set_telegram_webhook():
    try:
        resp = requests.get(f"https://api.telegram.org/bot{TOKEN}/setWebhook?url={WEBHOOK_URL}")
        if resp.status_code == 200:
            print("[WEBHOOK CONFIGURADO COM SUCESSO]")
        else:
            print(f"[ERRO AO CONFIGURAR WEBHOOK] Status: {resp.status_code}, {resp.text}")
    except Exception as e:
        print(f"[ERRO AO CONFIGURAR WEBHOOK]: {e}")

set_telegram_webhook()

def get_emoji_motivo(motivo):
    motivo = motivo.strip().lower()
    if "pedido de demissão" in motivo:
        return "❗"  
    elif "demissão s/justa causa" in motivo:
        return "📄" 
    elif "término de contrato" in motivo:
        return "❌"  
    else:
        return "⚠️"  

def connect_sheet():
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, scopes)
    client = gspread.authorize(creds)
    return client.open(SHEET_NAME).sheet1

def get_ultima_resposta_formatada():
    records = connect_sheet().get_all_records()
    if not records:
        return "Nenhum registro de demissão encontrado."
    
    latest_answer = records[-1]
    motivo = latest_answer.get('Motivo da demissão', 'Não especificado')
    emoji = get_emoji_motivo(motivo)
    
    return (
        f"Nome: {latest_answer.get('Nome Completo do Colaborador', 'N/A')}\n"
        f"Loja: {latest_answer.get('Unidade da Loja', 'N/A')}\n"
        f"*Data Demissão:** {latest_answer.get('Data Demissão', 'N/A')}*\n"
        f"Motivo: {motivo} {emoji}\n"
        f"*Aviso?:** {latest_answer.get('Vai cumprir aviso?', 'N/A')}*\n\n"
        "Selecione Uma Opção:"
    )

def get_funcionarios_em_aviso():
    records = connect_sheet().get_all_records()
    em_aviso = [
        f"• *{r['Nome Completo do Colaborador']}*\n{r['Unidade da Loja']}\n*{r['Término Aviso']}*\n" 
        for r in records if str(r.get("Vai cumprir aviso?")).strip().lower() == "sim"
    ]
    if not em_aviso: 
        return "Nenhum funcionário está cumprindo aviso no momento."
    return "*Colaboradores em Aviso Prévio  📢*\n\n" + "\n".join(em_aviso)

def get_ultimas_demissoes_formatadas(limit=5):
    records = connect_sheet().get_all_records()
    if not records: 
        return "Nenhum registro de demissão encontrado."
    
    ultimas_demissoes = records[-limit:]
    msg = "*Últimas 5 Demissões Registradas 📋*\n\n"
    for demissao in reversed(ultimas_demissoes):
        motivo = demissao.get('Motivo da demissão', 'N/A')
        emoji = get_emoji_motivo(motivo)
        msg += (
            f"*Nome:* {demissao.get('Nome Completo do Colaborador', 'N/A')}\n"
            f"*Loja:* {demissao.get('Unidade da Loja', 'N/A')}\n"
            f"*Motivo:* {motivo} {emoji}\n"
            f"*Cargo:* {demissao.get('Cargo do Colaborador', 'N/A')}\n\n"
        )
    return msg

def build_menu_principal():
    keyboard = [
        [InlineKeyboardButton("Colaboradores em Aviso", callback_data="ver_avisos")],
        [InlineKeyboardButton("Últimas Demissões", callback_data="ver_demissoes")]
    ]
    return InlineKeyboardMarkup(keyboard)

def build_menu_voltar():
    keyboard = [[InlineKeyboardButton("Voltar ao Menu ⬅️", callback_data="voltar_menu")]]
    return InlineKeyboardMarkup(keyboard)

async def handle_update(update: Update):
    if not update.callback_query: 
        return
    query = update.callback_query
    await query.answer()
    
    try:
        if query.data == "ver_avisos":
            texto = get_funcionarios_em_aviso()
            await query.edit_message_text(text=texto, reply_markup=build_menu_voltar(), parse_mode='Markdown')
        elif query.data == "ver_demissoes":
            texto = get_ultimas_demissoes_formatadas()
            await query.edit_message_text(text=texto, reply_markup=build_menu_voltar(), parse_mode='Markdown')
        elif query.data == "voltar_menu":
            texto_original = f"*Novo Processo de Desligamento* 🚨\n\n{get_ultima_resposta_formatada()}"
            await query.edit_message_text(text=texto_original, reply_markup=build_menu_principal(), parse_mode='Markdown')
    except Exception:
        print("[ERRO NO HANDLE_UPDATE]")
        traceback.print_exc()

def send_new_submission_message_sync():
    texto_mensagem = f"*Novo Processo de Desligamento* 🚨\n\n{get_ultima_resposta_formatada()}"
    try:
        resp = bot.send_message(
            chat_id=CHAT_ID,
            text=texto_mensagem,
            reply_markup=build_menu_principal(),
            parse_mode='Markdown'
        )
        print("[MENSAGEM ENVIADA]", resp)
    except Exception:
        print("[ERRO AO ENVIAR MENSAGEM]")
        traceback.print_exc()

@app.route("/novo-formulario", methods=["POST"])
def new_form_submission():
    try:
        threading.Thread(target=send_new_submission_message_sync).start()
        return "Notificação agendada com sucesso.", 200
    except Exception as e:
        print(f"[ERRO] /novo-formulario: {e}")
        return "Erro interno no servidor.", 500


@app.route("/webhook/<token>", methods=["POST"])
def telegram_webhook(token):
    if token != TOKEN:
        return "Token inválido", 403
    try:
        update_data = Update.de_json(request.json, bot)
        threading.Thread(target=lambda: asyncio.run(handle_update(update_data)), daemon=True).start()
        return "OK", 200
    except Exception:
        print("[ERRO NO /webhook]")
        traceback.print_exc()
        return "Erro interno no servidor.", 500

