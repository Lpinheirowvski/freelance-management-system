import json
import os
import math
import tempfile
from datetime import datetime

ARQUIVO = "freelancers.json"
META_MENSAL = 1000


def carregar_dados():
    if os.path.exists(ARQUIVO):
        try:
            with open(ARQUIVO, "r", encoding="utf-8") as arquivo:
                return json.load(arquivo)
        except (json.JSONDecodeError, OSError) as exc:
            raise ValueError("Erro ao carregar dados. Arquivo preservado; corrija antes de continuar.") from exc

    return []


def salvar_dados(clientes):
    pasta = os.path.dirname(os.path.abspath(ARQUIVO))
    caminho_temporario = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=pasta, delete=False) as arquivo:
            caminho_temporario = arquivo.name
            json.dump(clientes, arquivo, indent=4, ensure_ascii=False, allow_nan=False)
            arquivo.flush()
            os.fsync(arquivo.fileno())
        os.replace(caminho_temporario, ARQUIVO)
    finally:
        if caminho_temporario and os.path.exists(caminho_temporario):
            os.unlink(caminho_temporario)


def linha():
    print("=" * 55)


def titulo(texto):
    print()
    linha()
    print(texto.center(55))
    linha()


def cadastrar_cliente(clientes):
    titulo("CADASTRAR NOVO FREELANCE")

    nome = input("Nome do cliente: ").strip()
    projeto = input("Nome do projeto: ").strip()

    if not nome or not projeto:
        print("Nome e projeto sao obrigatorios.")
        return

    try:
        horas = float(input("Horas trabalhadas: "))
        valor_hora = float(input("Valor por hora (USD): "))

        if not math.isfinite(horas) or not math.isfinite(valor_hora) or horas <= 0 or valor_hora < 0:
            print("Valores invalidos!")
            return

    except ValueError:
        print("Digite apenas numeros!")
        return

    total = round(horas * valor_hora, 2)

    cliente = {
        "id": max((c["id"] for c in clientes), default=0) + 1,
        "nome": nome,
        "projeto": projeto,
        "horas": horas,
        "valor_hora": valor_hora,
        "total": total,
        "pago": False,
        "data": datetime.now().strftime("%d/%m/%Y"),
    }

    clientes.append(cliente)
    salvar_dados(clientes)

    print()
    print("Cliente cadastrado com sucesso!")
    print(f"Valor do projeto: US$ {total:.2f}")


def listar_clientes(clientes):
    titulo("LISTA DE PROJETOS")

    if not clientes:
        print("Nenhum projeto cadastrado.")
        return

    for cliente in clientes:
        status = "PAGO" if cliente["pago"] else "PENDENTE"

        print(f"\nID: {cliente['id']}")
        print(f"Cliente: {cliente['nome']}")
        print(f"Projeto: {cliente['projeto']}")
        print(f"Valor: US$ {cliente['total']:.2f}")
        print(f"Status: {status}")
        print("-" * 55)


def registrar_pagamento(clientes):
    titulo("REGISTRAR PAGAMENTO")

    listar_clientes(clientes)

    try:
        codigo = int(input("\nID do projeto: "))
    except ValueError:
        print("ID invalido!")
        return

    for cliente in clientes:
        if cliente["id"] == codigo:
            if cliente["pago"]:
                print("Este projeto ja foi pago!")
                return

            cliente["pago"] = True
            cliente["data_pagamento"] = datetime.now().strftime("%d/%m/%Y")
            salvar_dados(clientes)

            print("Pagamento registrado!")
            return

    print("Projeto nao encontrado.")


def recebido_no_mes(clientes, mes=None):
    mes = mes or datetime.now().strftime("%m/%Y")
    total = 0
    for cliente in clientes:
        if cliente.get("pago") and cliente.get("data_pagamento"):
            try:
                data = datetime.strptime(cliente["data_pagamento"], "%d/%m/%Y")
            except (ValueError, TypeError):
                continue
            if data.strftime("%m/%Y") == mes:
                total += cliente["total"]
    return total


def relatorio_financeiro(clientes):
    titulo("RELATORIO FINANCEIRO")

    faturamento = sum(c["total"] for c in clientes)

    recebido = sum(c["total"] for c in clientes if c["pago"])

    pendente = faturamento - recebido

    projetos = len(clientes)

    print(f"Total de projetos: {projetos}")
    print(f"Faturamento contratado: US$ {faturamento:.2f}")
    print(f"Total recebido: US$ {recebido:.2f}")
    print(f"Pagamentos pendentes: US$ {pendente:.2f}")

    print()
    linha()
    print("META FINANCEIRA")
    linha()

    recebido_mes = recebido_no_mes(clientes)
    progresso = min((recebido_mes / META_MENSAL) * 100, 100)
    print(f"Recebido neste mes: US$ {recebido_mes:.2f}")
    print("Pagamentos sem data nao contam para a meta mensal.")

    print(f"Meta: US$ {META_MENSAL:.2f}")
    print(f"Progresso: {progresso:.1f}%")

    barras = int(progresso / 5)

    print("[" + "#" * barras + "-" * (20 - barras) + "]")

    if recebido_mes >= META_MENSAL:
        print("META ATINGIDA! DALE!")
    elif recebido_mes >= META_MENSAL / 2:
        print("Mais da metade da meta!")
    else:
        print("Continuar trabalhando!")


def ranking_clientes(clientes):
    titulo("RANKING DE PROJETOS")

    if not clientes:
        print("Nenhum projeto cadastrado.")
        return

    ranking = sorted(clientes, key=lambda c: c["total"], reverse=True)

    for posicao, cliente in enumerate(ranking, start=1):
        print(f"{posicao}. {cliente['nome']} - US$ {cliente['total']:.2f}")


def menu():
    try:
        clientes = carregar_dados()
    except ValueError as exc:
        print(str(exc))
        return

    while True:
        titulo("FREELANCER MANAGER v1.0")

        print("1 - Cadastrar cliente")
        print("2 - Listar projetos")
        print("3 - Registrar pagamento")
        print("4 - Relatorio financeiro")
        print("5 - Ranking de projetos")
        print("6 - Sair")

        print()
        opcao = input("Escolha uma opcao: ")

        if opcao == "1":
            cadastrar_cliente(clientes)

        elif opcao == "2":
            listar_clientes(clientes)

        elif opcao == "3":
            registrar_pagamento(clientes)

        elif opcao == "4":
            relatorio_financeiro(clientes)

        elif opcao == "5":
            ranking_clientes(clientes)

        elif opcao == "6":
            print("Encerrando sistema...")
            break

        else:
            print("Opcao invalida!")

        input("\nPressione ENTER para continuar...")


if __name__ == "__main__":
    menu()
