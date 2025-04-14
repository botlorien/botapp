import time
import threading
from botapp import BotApp

# 1. Inicializa o app e conecta com o banco
app = BotApp('BotsCarvalima')

# 2. Registra o bot antes de usar qualquer task
app.set_bot(
    bot_name='Bot_de_teste',
    bot_description='Bot de testes de desenvolvimento',
    bot_version='0.1.0',
    bot_department='TI'
)

# 3. Agora o decorador @app.task já pode ser usado
@app.task
def exemplo_sucess():
    """Descrição da tarefa"""
    print("Executando a tarefa exemplo sucesso")
    return "Sucesso!"

@app.task
def exemplo_running():
    """Descrição da tarefa"""
    print("Executando a tarefa exemplo 30 s em execução")
    time.sleep(30)
    return "Sucesso!"

@app.task
def exemplo_failed():
    """Descrição da tarefa"""
    print("Executando a tarefa exemplo com falha")
    raise ValueError("Erro de exemplo")


# 4. Executa a task
exemplo_sucess()

# Executa a tarefa em um thread separado
thread = threading.Thread(target=exemplo_running)
thread.start()
try:
    exemplo_failed()
except Exception as e:
    print(f"Erro capturado: {e}")

# Novo app para testar o bot inativo

app2 = BotApp('BotsCarvalima')

app2.set_bot(
    bot_name='Bot_teste_inativo',
    bot_description='Bot de testes de desenvolvimento',
    bot_version='0.1.0',
    bot_department='TI-Atualizada'
)

app2.bot_instance.is_active = True
app2.bot_instance.save()

@app2.task
def exemplo_sucess():
    """Descrição da tarefa Atualizada"""
    print("Executando a tarefa exemplo sucesso")
    return "Sucesso!"


exemplo_sucess()

app2.bot_instance.is_active = False
app2.bot_instance.save()

exemplo_sucess()