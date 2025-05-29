from django.core.management.base import BaseCommand
from django.db import IntegrityError
from monitor.models import TermoMonitorado # Importe seu modelo

# Lista de normas e termos relevantes (NÍVEL FEDERAL E ESTADUAL DO PIAUÍ)
# Você pode expandir e refinar esta lista conforme sua necessidade.
NORMAS_E_TERMOS = [
    # --- NORMAS FEDERAIS CHAVE ---
    {"termo": "LC 101/00", "tipo": "NORMA", "variacoes": "Lei de Responsabilidade Fiscal, LRF, Lei Complementar 101/2000", "prioridade": 5},
    {"termo": "LC 123/06", "tipo": "NORMA", "variacoes": "Simples Nacional, Lei Complementar 123/2006, Estatuto da Microempresa", "prioridade": 4},
    {"termo": "Lei 4.320/64", "tipo": "NORMA", "variacoes": "Normas Gerais de Direito Financeiro, Lei 4320", "prioridade": 5},
    {"termo": "Lei 6.404/76", "tipo": "NORMA", "variacoes": "Lei das S/A, Lei das Sociedades por Ações", "prioridade": 4},
    {"termo": "Decreto 9.580/18", "tipo": "NORMA", "variacoes": "RIR/2018, Novo Regulamento do Imposto de Renda, Regulamento do IR", "prioridade": 5},
    {"termo": "EC 132/23", "tipo": "NORMA", "variacoes": "Reforma Tributária, Emenda Constitucional 132/2023", "prioridade": 5},

    # --- NORMAS ESTADUAIS DO PIAUÍ CHAVE ---
    {"termo": "Lei 4.257/89", "tipo": "NORMA", "variacoes": "Lei do ICMS PI, Lei Estadual 4257/1989 Piauí", "prioridade": 5},
    {"termo": "Decreto 21.866/23", "tipo": "NORMA", "variacoes": "RICMS PI, Regulamento do ICMS Piauí, Decreto Estadual 21866/2023", "prioridade": 5},
    {"termo": "Lei 6.949/17", "tipo": "NORMA", "variacoes": "PAT PI, Processo Administrativo Tributário Piauí, Lei Estadual 6949/2017", "prioridade": 4},
    {"termo": "Lei 4.254/88", "tipo": "NORMA", "variacoes": "Taxas Estaduais PI, Lei Estadual 4254/1988", "prioridade": 3},
    {"termo": "Lei 4.261/89", "tipo": "NORMA", "variacoes": "ITCMD PI, Lei Estadual 4261/1989", "prioridade": 3},
    {"termo": "Lei 4.548/92", "tipo": "NORMA", "variacoes": "IPVA PI, Lei Estadual 4548/1992", "prioridade": 3},

    # --- TERMOS GENÉRICOS RELEVANTES (CONTÁBIL/FISCAL) ---
    {"termo": "ICMS", "tipo": "TEXTO", "variacoes": "Imposto sobre Circulação de Mercadorias e Serviços", "prioridade": 5},
    {"termo": "Substituição Tributária", "tipo": "TEXTO", "variacoes": "ST, ICMS-ST", "prioridade": 5},
    {"termo": "PIS", "tipo": "TEXTO", "variacoes": "Programa de Integração Social", "prioridade": 4},
    {"termo": "COFINS", "tipo": "TEXTO", "variacoes": "Contribuição para o Financiamento da Seguridade Social", "prioridade": 4},
    {"termo": "Imposto de Renda", "tipo": "TEXTO", "variacoes": "IR, IRPF, IRPJ", "prioridade": 4},
    {"termo": "Obrigação Acessória", "tipo": "TEXTO", "variacoes": "Obrigações Acessórias", "prioridade": 3},
    {"termo": "SPED", "tipo": "TEXTO", "variacoes": "Sistema Público de Escrituração Digital, EFD, ECD, ECF", "prioridade": 4},
    {"termo": "SEFAZ PI", "tipo": "TEXTO", "variacoes": "Secretaria da Fazenda do Piauí", "prioridade": 5},
    {"termo": "UNATRI", "tipo": "TEXTO", "variacoes": "Unidade de Administração Tributária", "prioridade": 4}, # Específico do Piauí
    {"termo": "UNIFIS", "tipo": "TEXTO", "variacoes": "Unidade de Fiscalização", "prioridade": 4}, # Específico do Piauí
    {"termo": "Portaria SEFAZ", "tipo": "TEXTO", "variacoes": "Portaria da Secretaria da Fazenda", "prioridade": 3},
    {"termo": "Ato Normativo SEFAZ", "tipo": "TEXTO", "variacoes": "Ato Normativo da Secretaria da Fazenda", "prioridade": 3},
    {"termo": "Regime Especial", "tipo": "TEXTO", "variacoes": "Regimes Especiais de Tributação", "prioridade": 3},
    {"termo": "Alíquota", "tipo": "TEXTO", "variacoes": "Alíquotas", "prioridade": 3},
    {"termo": "Base de Cálculo", "tipo": "TEXTO", "variacoes": "BC", "prioridade": 3},
    {"termo": "Crédito Fiscal", "tipo": "TEXTO", "variacoes": "Créditos Fiscais", "prioridade": 4},
    {"termo": "Débito Fiscal", "tipo": "TEXTO", "variacoes": "Débitos Fiscais", "prioridade": 4},
    {"termo": "Nota Fiscal Eletrônica", "tipo": "TEXTO", "variacoes": "NF-e, NFe", "prioridade": 3},
    {"termo": "Manifesto Eletrônico de Documentos Fiscais", "tipo": "TEXTO", "variacoes": "MDF-e, MDFe", "prioridade": 3},
    {"termo": "Conhecimento de Transporte Eletrônico", "tipo": "TEXTO", "variacoes": "CT-e, CTe", "prioridade": 3},
    # Adicione mais termos e normas conforme necessário
]

class Command(BaseCommand):
    help = 'Popula o banco de dados com Termos Monitorados contábeis/fiscais relevantes.'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Iniciando a população de Termos Monitorados...'))
        termos_criados = 0
        termos_existentes = 0

        for item in NORMAS_E_TERMOS:
            try:
                termo_obj, created = TermoMonitorado.objects.get_or_create(
                    termo=item['termo'],
                    defaults={
                        'tipo': item['tipo'],
                        'variacoes': item.get('variacoes', ''), # .get() para o caso de não haver variações
                        'prioridade': item.get('prioridade', 3), # Prioridade padrão 3 se não especificada
                        'ativo': True
                    }
                )
                if created:
                    self.stdout.write(self.style.SUCCESS(f"Criado: {termo_obj.termo} ({termo_obj.get_tipo_display()})"))
                    termos_criados += 1
                else:
                    # Opcional: atualizar campos se o termo já existir e você quiser garantir que os dados estão corretos
                    # termo_obj.tipo = item['tipo']
                    # termo_obj.variacoes = item.get('variacoes', '')
                    # termo_obj.prioridade = item.get('prioridade', 3)
                    # termo_obj.ativo = True
                    # termo_obj.save()
                    # self.stdout.write(self.style.WARNING(f"Já existe (verificado/atualizado): {termo_obj.termo}"))
                    self.stdout.write(self.style.WARNING(f"Já existe: {termo_obj.termo}"))
                    termos_existentes += 1
            except IntegrityError as e:
                self.stderr.write(self.style.ERROR(f"Erro de integridade ao tentar criar '{item['termo']}': {e}"))
            except Exception as e:
                self.stderr.write(self.style.ERROR(f"Erro ao processar '{item['termo']}': {e}"))

        self.stdout.write(self.style.SUCCESS(f"\nPopulação concluída!"))
        self.stdout.write(self.style.SUCCESS(f"{termos_criados} termos criados."))
        self.stdout.write(self.style.WARNING(f"{termos_existentes} termos já existiam."))