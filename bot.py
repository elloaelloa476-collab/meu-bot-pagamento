import discord
from discord.ext import commands
import imaplib
import email
from email.header import decode_header
import re
import os
from dotenv import load_dotenv

load_dotenv()

# Configurações
TOKEN = os.getenv('DISCORD_TOKEN')
GMAIL_EMAIL = os.getenv('GMAIL_EMAIL')
GMAIL_PASSWORD = os.getenv('GMAIL_PASSWORD')

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Listas de controle
pending_payments = {}
servidores_permitidos = set()       # IDs dos servidores liberados
categorias_permitidas = {}          # {servidor_id: {categoria_id, ...}}

def ler_pagamentos_gmail():
    pagamentos = []
    try:
        mail = imaplib.IMAP4_SSL('imap.gmail.com')
        mail.login(GMAIL_EMAIL, GMAIL_PASSWORD)
        mail.select('inbox')

        status, messages = mail.search(None, '(UNSEEN SUBJECT "Pix recebido" OR SUBJECT "Pagamento confirmado" OR SUBJECT "Transferência recebida")')
        
        if status != 'OK':
            return pagamentos

        email_ids = messages[0].split()
        
        for e_id in email_ids[-10:]:
            status, msg_data = mail.fetch(e_id, '(RFC822)')
            for response_part in msg_data:
                if isinstance(response_part, tuple):
                    msg = email.message_from_bytes(response_part[1])
                    assunto, encoding = decode_header(msg['Subject'])[0]
                    if isinstance(assunto, bytes):
                        assunto = assunto.decode(encoding or 'utf-8')
                    
                    corpo = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            if part.get_content_type() == 'text/plain':
                                corpo = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                    else:
                        corpo = msg.get_payload(decode=True).decode('utf-8', errors='ignore')
                    
                    padroes = [
                        r'de\s+([A-Za-zÀ-ú]+\s+[A-Za-zÀ-ú]+)',
                        r'remetente:\s*([A-Za-zÀ-ú]+\s+[A-Za-zÀ-ú]+)',
                        r'nome:\s*([A-Za-zÀ-ú]+\s+[A-Za-zÀ-ú]+)'
                    ]
                    
                    for padrao in padroes:
                        match = re.search(padrao, corpo, re.IGNORECASE)
                        if match:
                            nome = match.group(1).strip().upper()
                            pagamentos.append(nome)
                            break
        
        mail.logout()
    except Exception as e:
        print(f"❌ Erro ao ler Gmail: {e}")
    
    return pagamentos

@bot.event
async def on_ready():
    print(f'🤖 Bot online como {bot.user}')
    print('----------------------------------')
    print(f'🌐 Servidores permitidos: {servidores_permitidos if servidores_permitidos else "Nenhum cadastrado"}')

# Bloqueia comandos em servidores não autorizados
@bot.check
async def verificar_servidor(ctx):
    if not ctx.guild:
        return False
    return ctx.guild.id in servidores_permitidos

# Comando executado automaticamente em servidores não liberados
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CheckFailure):
        await ctx.send('❌ Esse bot não está autorizado neste servidor. Contate um administrador.')

# === COMANDOS DE ADMINISTRAÇÃO ===

# Adicionar servidor permitido
@bot.command(name='addservidor', help='(ADM BOT) Adiciona um servidor: !addservidor ID_SERVIDOR')
@commands.is_owner()
async def add_servidor(ctx, servidor_id: int):
    servidores_permitidos.add(servidor_id)
    categorias_permitidas[servidor_id] = set()
    await ctx.send(f'✅ Servidor `{servidor_id}` autorizado com sucesso!')
    print(f'🌐 Servidor {servidor_id} adicionado.')

# Remover servidor permitido
@bot.command(name='remservidor', help='(ADM BOT) Remove um servidor: !remservidor ID_SERVIDOR')
@commands.is_owner()
async def rem_servidor(ctx, servidor_id: int):
    if servidor_id in servidores_permitidos:
        servidores_permitidos.remove(servidor_id)
        categorias_permitidas.pop(servidor_id, None)
        await ctx.send(f'❌ Servidor `{servidor_id}` removido!')
    else:
        await ctx.send(f'Esse servidor não está na lista.')

# Listar servidores permitidos
@bot.command(name='listservidores', help='(ADM BOT) Lista todos os servidores autorizados')
@commands.is_owner()
async def list_servidores(ctx):
    if servidores_permitidos:
        await ctx.send(f'📋 Servidores autorizados:\n' + '\n'.join(f'• `{sid}`' for sid in servidores_permitidos))
    else:
        await ctx.send('⚠️ Nenhum servidor autorizado ainda!')

# Adicionar categoria permitida NO SERVIDOR ATUAL
@bot.command(name='addcategoria', help='(ADM) Adiciona categoria neste servidor: !addcategoria ID_CATEGORIA')
@commands.has_permissions(administrator=True)
async def add_categoria(ctx, categoria_id: int):
    servidor_id = ctx.guild.id
    if servidor_id not in categorias_permitidas:
        categorias_permitidas[servidor_id] = set()
    categorias_permitidas[servidor_id].add(categoria_id)
    await ctx.send(f'✅ Categoria `{categoria_id}` liberada neste servidor!')

# Remover categoria permitida
@bot.command(name='remcategoria', help='(ADM) Remove categoria: !remcategoria ID_CATEGORIA')
@commands.has_permissions(administrator=True)
async def rem_categoria(ctx, categoria_id: int):
    servidor_id = ctx.guild.id
    if servidor_id in categorias_permitidas and categoria_id in categorias_permitidas[servidor_id]:
        categorias_permitidas[servidor_id].remove(categoria_id)
        await ctx.send(f'❌ Categoria `{categoria_id}` removida!')
    else:
        await ctx.send(f'Essa categoria não está liberada neste servidor.')

# Listar categorias do servidor atual
@bot.command(name='listacategorias', help='(ADM) Lista categorias deste servidor')
@commands.has_permissions(administrator=True)
async def list_categorias(ctx):
    servidor_id = ctx.guild.id
    cats = categorias_permitidas.get(servidor_id, set())
    if cats:
        await ctx.send(f'📋 Categorias liberadas:\n' + '\n'.join(f'• `{cid}`' for cid in cats))
    else:
        await ctx.send('⚠️ Nenhuma categoria liberada ainda.')

# === COMANDO PRINCIPAL ===

@bot.command(name='verificar', help='Verifica pagamento: !verificar Nome Sobrenome')
async def verificar_pagamento(ctx, *, nome_completo):
    servidor_id = ctx.guild.id
    categoria_atual = ctx.channel.category_id
    
    # Verifica se tem categorias liberadas no servidor
    cats_servidor = categorias_permitidas.get(servidor_id, set())
    if not cats_servidor:
        await ctx.send('⚠️ Nenhuma categoria foi liberada ainda neste servidor. Peça para um administrador configurar!')
        return
    
    # Verifica se está na categoria permitida
    if categoria_atual not in cats_servidor:
        await ctx.send('❌ Esse comando só funciona dentro das categorias autorizadas!')
        return

    nome_completo = nome_completo.strip().upper()
    usuario_id = ctx.author.id

    await ctx.send(f'🔍 Verificando pagamento de **{nome_completo}**...')
    
    pagamentos = ler_pagamentos_gmail()
    
    if nome_completo in pagamentos:
        pending_payments[usuario_id] = {
            'nome': nome_completo,
            'autor': ctx.author,
            'confirmado': True
        }
        
        await ctx.send(f'✅ Pagamento confirmado para **{nome_completo}**! Aguardando o outro jogador...')
        await checar_ambos_pagamentos(ctx)
    else:
        await ctx.send(f'❌ Pagamento não encontrado para **{nome_completo}**.')

async def checar_ambos_pagamentos(ctx):
    confirmados = [p for p in pending_payments.values() if p['confirmado']]
    
    if len(confirmados) >= 2:
        await ctx.send('✅✅ AMBOS OS PAGAMENTOS CONFIRMADOS!')
        await ctx.send('.cs')
        pending_payments.clear()

@bot.command(name='limpar', help='(ADM) Limpa pagamentos pendentes')
@commands.has_permissions(administrator=True)
async def limpar(ctx):
    pending_payments.clear()
    await ctx.send('🔄 Pagamentos limpos!')

bot.run(TOKEN)