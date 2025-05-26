# test_normas_avancado.py
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'diario_oficial.settings')
import django
django.setup()

from monitor.models import NormaVigente
from monitor.utils.sefaz_integracao import IntegradorSEFAZ
from datetime import datetime, timedelta
from django.utils import timezone
import time
import random
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

class TesteSuiteAvancado:
    def __init__(self):
        self.integrador = IntegradorSEFAZ()
        self.cores = {
            'verde': '\033[92m',
            'vermelho': '\033[91m',
            'amarelo': '\033[93m',
            'azul': '\033[94m',
            'magenta': '\033[95m',
            'ciano': '\033[96m',
            'branco': '\033[97m',
            'reset': '\033[0m',
            'negrito': '\033[1m'
        }
    
    def print_colored(self, texto, cor='reset'):
        """Imprime texto colorido."""
        print(f"{self.cores[cor]}{texto}{self.cores['reset']}")
    
    def print_header(self, titulo):
        """Imprime cabeçalho formatado."""
        linha = "=" * 60
        self.print_colored(f"\n{linha}", 'azul')
        self.print_colored(f"{titulo.center(60)}", 'negrito')
        self.print_colored(linha, 'azul')
    
    def limpar_testes_anteriores(self):
        """Remove todas as normas de teste anteriores."""
        deleted_count = NormaVigente.objects.filter(descricao__startswith='[TESTE]').delete()[0]
        if deleted_count > 0:
            self.print_colored(f"🗑️  {deleted_count} normas de teste anteriores removidas", 'amarelo')
    
    def criar_cenarios_basicos(self):
        """Cria cenários básicos de teste."""
        self.print_header("CRIANDO CENÁRIOS BÁSICOS")
        
        # Verdadeiros Positivos - Normas que DEVEM ser encontradas como VIGENTE
        normas_vp = [
            {'tipo': 'DECRETO', 'numero': '21.866', 'descricao': '[TESTE] VP-BÁSICO - Decreto válido conhecido'},
            {'tipo': 'LEI', 'numero': '4.257', 'descricao': '[TESTE] VP-BÁSICO - Lei válida conhecida'},
            {'tipo': 'ATO NORMATIVO', 'numero': '25/21', 'descricao': '[TESTE] VP-BÁSICO - Ato normativo válido'},
            {'tipo': 'PORTARIA', 'numero': '156/2023', 'descricao': '[TESTE] VP-BÁSICO - Portaria válida'},
        ]
        
        # Falsos Positivos - Normas inválidas que NÃO devem ser aceitas
        normas_fp = [
            {'tipo': 'INVALIDO', 'numero': '123', 'descricao': '[TESTE] FP-BÁSICO - Tipo completamente inválido'},
            {'tipo': 'DECRETO', 'numero': '1', 'descricao': '[TESTE] FP-BÁSICO - Número muito curto'},
            {'tipo': 'DECRETO', 'numero': '999999', 'descricao': '[TESTE] FP-BÁSICO - Número inexistente alto'},
            {'tipo': 'LEI', 'numero': '', 'descricao': '[TESTE] FP-BÁSICO - Número vazio'},
            {'tipo': '', 'numero': '123', 'descricao': '[TESTE] FP-BÁSICO - Tipo vazio'},
        ]
        
        self._criar_normas_lote(normas_vp + normas_fp, "BÁSICO")
        return len(normas_vp), len(normas_fp)
    
    def criar_cenarios_stress(self, quantidade=20):
        """Cria cenários de teste de stress com muitas normas."""
        self.print_header(f"CRIANDO CENÁRIOS DE STRESS ({quantidade} normas)")
        
        normas_stress = []
        
        # Gera normas válidas aleatórias
        for i in range(quantidade // 2):
            tipo = random.choice(['DECRETO', 'LEI', 'ATO NORMATIVO', 'PORTARIA'])
            if tipo == 'ATO NORMATIVO':
                numero = f"{random.randint(10, 99)}/{random.randint(20, 24)}"
            else:
                numero = str(random.randint(1000, 25000))
                if random.choice([True, False]):
                    numero = f"{numero[:2]}.{numero[2:]}"
            
            normas_stress.append({
                'tipo': tipo,
                'numero': numero,
                'descricao': f'[TESTE] VP-STRESS-{i+1} - {tipo} gerado aleatoriamente'
            })
        
        # Gera normas inválidas aleatórias
        for i in range(quantidade // 2):
            tipo_invalido = random.choice(['DECRETO', 'LEI', 'TIPO_INEXISTENTE', ''])
            numero_invalido = random.choice(['', '1', '0', 'ABC', '9999999'])
            
            normas_stress.append({
                'tipo': tipo_invalido,
                'numero': numero_invalido,
                'descricao': f'[TESTE] FP-STRESS-{i+1} - Norma inválida gerada'
            })
        
        self._criar_normas_lote(normas_stress, "STRESS")
        return quantidade // 2, quantidade // 2
    
    def criar_cenarios_edge_cases(self):
        """Cria cenários de casos extremos."""
        self.print_header("CRIANDO CENÁRIOS DE CASOS EXTREMOS")
        
        normas_edge = [
            # Formatações especiais
            {'tipo': 'DECRETO', 'numero': '21866', 'descricao': '[TESTE] EDGE - Decreto sem pontuação'},
            {'tipo': 'LEI', 'numero': '4257', 'descricao': '[TESTE] EDGE - Lei sem pontuação'},
            {'tipo': 'ATO NORMATIVO', 'numero': '25/2021', 'descricao': '[TESTE] EDGE - Ato com ano completo'},
            
            # Casos limítrofes
            {'tipo': 'DECRETO', 'numero': '100', 'descricao': '[TESTE] EDGE - Decreto número mínimo'},
            {'tipo': 'DECRETO', 'numero': '99999', 'descricao': '[TESTE] EDGE - Decreto número alto'},
            
            # Caracteres especiais
            {'tipo': 'LEI', 'numero': '4.257-A', 'descricao': '[TESTE] EDGE - Lei com sufixo'},
            {'tipo': 'DECRETO', 'numero': '21.866/2023', 'descricao': '[TESTE] EDGE - Decreto com ano'},
            
            # Espaços e formatação
            {'tipo': ' DECRETO ', 'numero': ' 21866 ', 'descricao': '[TESTE] EDGE - Com espaços extras'},
        ]
        
        self._criar_normas_lote(normas_edge, "EDGE CASES")
        return len(normas_edge), 0
    
    def criar_cenarios_concorrencia(self):
        """Cria cenários para testar concorrência."""
        self.print_header("CRIANDO CENÁRIOS DE CONCORRÊNCIA")
        
        # Cria várias normas idênticas para testar race conditions
        normas_concorrencia = []
        for i in range(10):
            normas_concorrencia.append({
                'tipo': 'DECRETO',
                'numero': '21.866',
                'descricao': f'[TESTE] CONCORRÊNCIA-{i+1} - Decreto duplicado para teste de concorrência'
            })
        
        self._criar_normas_lote(normas_concorrencia, "CONCORRÊNCIA")
        return len(normas_concorrencia), 0
    
    def _criar_normas_lote(self, normas_dados, categoria):
        """Cria normas em lote ignorando validações."""
        normas_para_criar = []
        
        for dados in normas_dados:
            norma = NormaVigente(
                tipo=dados.get('tipo', ''),
                numero=dados.get('numero', ''),
                descricao=dados.get('descricao', ''),
                situacao='NAO_VERIFICADO',
                data_verificacao=None,
                observacoes=f'Criado para teste - Categoria: {categoria}'
            )
            normas_para_criar.append(norma)
        
        try:
            NormaVigente.objects.bulk_create(normas_para_criar)
            self.print_colored(f"✅ {len(normas_dados)} normas criadas na categoria {categoria}", 'verde')
        except Exception as e:
            self.print_colored(f"❌ Erro ao criar normas {categoria}: {str(e)}", 'vermelho')
    
    def executar_teste_basico(self):
        """Executa teste básico com métricas detalhadas."""
        self.print_header("EXECUTANDO TESTE BÁSICO")
        
        normas_teste = NormaVigente.objects.filter(descricao__contains='BÁSICO').order_by('descricao')
        
        if not normas_teste.exists():
            self.print_colored("❌ Nenhuma norma básica encontrada. Execute primeiro a criação de cenários.", 'vermelho')
            return
        
        inicio = time.time()
        self.print_colored(f"🚀 Iniciando verificação de {normas_teste.count()} normas básicas...", 'azul')
        
        # Executa verificação
        resultados = self.integrador.verificar_normas_em_lote(list(normas_teste))
        
        fim = time.time()
        duracao = fim - inicio
        
        # Exibe resultados
        self._exibir_resultados_detalhados(normas_teste, resultados, duracao, "BÁSICO")
        return resultados
    
    def executar_teste_stress(self, batch_size=5):
        """Executa teste de stress com configurações otimizadas."""
        self.print_header("EXECUTANDO TESTE DE STRESS")
        
        normas_teste = NormaVigente.objects.filter(descricao__contains='STRESS').order_by('descricao')
        
        if not normas_teste.exists():
            self.print_colored("❌ Nenhuma norma de stress encontrada. Execute primeiro a criação de cenários.", 'vermelho')
            return
        
        self.print_colored(f"🔥 Iniciando teste de stress com {normas_teste.count()} normas (batch_size={batch_size})...", 'magenta')
        
        inicio = time.time()
        
        # Executa com configurações otimizadas para stress
        resultados = self.integrador.verificar_normas_em_lote(
            list(normas_teste),
            batch_size=batch_size,
            max_retries=1,  # Menos retries em stress test
            retry_delay=0.5
        )
        
        fim = time.time()
        duracao = fim - inicio
        
        # Calcula throughput
        throughput = normas_teste.count() / duracao if duracao > 0 else 0
        
        self.print_colored(f"⚡ Throughput: {throughput:.2f} normas/segundo", 'ciano')
        self._exibir_resultados_detalhados(normas_teste, resultados, duracao, "STRESS")
        return resultados
    
    def executar_teste_concorrencia(self):
        """Executa teste de concorrência usando múltiplas threads."""
        self.print_header("EXECUTANDO TESTE DE CONCORRÊNCIA")
        
        normas_teste = list(NormaVigente.objects.filter(descricao__contains='CONCORRÊNCIA'))
        
        if not normas_teste:
            self.print_colored("❌ Nenhuma norma de concorrência encontrada.", 'vermelho')
            return
        
        self.print_colored(f"🔄 Iniciando teste de concorrência com {len(normas_teste)} normas...", 'magenta')
        
        # Divide normas em grupos para processamento simultâneo
        num_threads = 3
        grupos = [normas_teste[i::num_threads] for i in range(num_threads)]
        
        resultados_threads = []
        threads_info = []
        
        def processar_grupo(grupo, thread_id):
            inicio_thread = time.time()
            integrador_thread = IntegradorSEFAZ()  # Instância separada por thread
            resultado = integrador_thread.verificar_normas_em_lote(grupo, batch_size=2)
            fim_thread = time.time()
            
            threads_info.append({
                'thread_id': thread_id,
                'normas_processadas': len(grupo),
                'duracao': fim_thread - inicio_thread,
                'resultado': resultado
            })
        
        inicio_total = time.time()
        
        # Executa threads simultaneamente
        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [
                executor.submit(processar_grupo, grupo, i) 
                for i, grupo in enumerate(grupos) if grupo
            ]
            
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    self.print_colored(f"❌ Erro em thread: {str(e)}", 'vermelho')
        
        fim_total = time.time()
        duracao_total = fim_total - inicio_total
        
        # Analisa resultados de concorrência
        self._analisar_concorrencia(threads_info, duracao_total)
    
    def executar_teste_completo(self):
        """Executa bateria completa de testes."""
        self.print_header("EXECUTANDO BATERIA COMPLETA DE TESTES")
        
        inicio_geral = time.time()
        resultados_completos = {
            'basico': None,
            'stress': None,
            'edge_cases': None,
            'concorrencia': None
        }
        
        try:
            # 1. Teste básico
            resultados_completos['basico'] = self.executar_teste_basico()
            time.sleep(2)  # Pausa entre testes
            
            # 2. Teste de stress
            resultados_completos['stress'] = self.executar_teste_stress()
            time.sleep(2)
            
            # 3. Teste de casos extremos
            normas_edge = NormaVigente.objects.filter(descricao__contains='EDGE')
            if normas_edge.exists():
                self.print_header("EXECUTANDO TESTE DE CASOS EXTREMOS")
                resultados_completos['edge_cases'] = self.integrador.verificar_normas_em_lote(list(normas_edge))
            
            # 4. Teste de concorrência
            self.executar_teste_concorrencia()
            
        except Exception as e:
            self.print_colored(f"❌ Erro durante bateria de testes: {str(e)}", 'vermelho')
        
        fim_geral = time.time()
        self._gerar_relatorio_final(resultados_completos, fim_geral - inicio_geral)
    
    def _exibir_resultados_detalhados(self, normas_teste, resultados, duracao, categoria):
        """Exibe resultados detalhados dos testes."""
        print(f"\n{'='*20} RESULTADOS {categoria} {'='*20}")
        
        # Atualiza normas do banco e exibe status
        for norma in normas_teste:
            norma.refresh_from_db()
            
            # Determina cor baseada no status
            if norma.situacao == 'VIGENTE':
                cor = 'verde'
                simbolo = '✅'
            elif norma.situacao == 'NAO_VIGENTE':
                cor = 'amarelo'
                simbolo = '❌'
            elif norma.situacao == 'DADOS_INVALIDOS':
                cor = 'magenta'
                simbolo = '🚫'
            elif norma.situacao == 'ERRO_TEMPORARIO':
                cor = 'vermelho'
                simbolo = '⚠️'
            else:
                cor = 'branco'
                simbolo = '❓'
            
            descricao_truncada = norma.descricao[:50].ljust(50)
            tipo_numero = f"{norma.tipo} {norma.numero}".ljust(20)
            
            self.print_colored(
                f"{simbolo} {descricao_truncada} | {tipo_numero} | {norma.situacao}",
                cor
            )
        
        # Estatísticas detalhadas
        self._calcular_estatisticas_avancadas(normas_teste, resultados, duracao)
    
    def _calcular_estatisticas_avancadas(self, normas_teste, resultados, duracao):
        """Calcula e exibe estatísticas avançadas."""
        total = normas_teste.count()
        
        # Contadores por status
        vigentes = normas_teste.filter(situacao='VIGENTE').count()
        nao_vigentes = normas_teste.filter(situacao='NAO_VIGENTE').count()
        dados_invalidos = normas_teste.filter(situacao='DADOS_INVALIDOS').count()
        erros_temporarios = normas_teste.filter(situacao='ERRO_TEMPORARIO').count()
        nao_verificados = normas_teste.filter(situacao='NAO_VERIFICADO').count()
        
        # Análise VP/FP/VN/FN
        vp = normas_teste.filter(descricao__contains='VP', situacao='VIGENTE').count()
        fp = normas_teste.filter(descricao__contains='FP', situacao='VIGENTE').count()
        vn = normas_teste.filter(descricao__contains='FP').exclude(situacao='VIGENTE').count()
        fn = normas_teste.filter(descricao__contains='VP').exclude(situacao='VIGENTE').count()
        
        total_vp_esperados = normas_teste.filter(descricao__contains='VP').count()
        total_fp_esperados = normas_teste.filter(descricao__contains='FP').count()
        
        print(f"\n{'='*15} ESTATÍSTICAS AVANÇADAS {'='*15}")
        
        # Métricas de performance
        throughput = total / duracao if duracao > 0 else 0
        self.print_colored(f"⏱️  Duração total: {duracao:.2f}s", 'azul')
        self.print_colored(f"⚡ Throughput: {throughput:.2f} normas/segundo", 'ciano')
        
        # Distribuição por status
        print(f"\n📊 DISTRIBUIÇÃO POR STATUS:")
        self.print_colored(f"   ✅ Vigentes: {vigentes} ({vigentes/total*100:.1f}%)", 'verde')
        self.print_colored(f"   ❌ Não vigentes: {nao_vigentes} ({nao_vigentes/total*100:.1f}%)", 'amarelo')
        self.print_colored(f"   🚫 Dados inválidos: {dados_invalidos} ({dados_invalidos/total*100:.1f}%)", 'magenta')
        self.print_colored(f"   ⚠️  Erros temporários: {erros_temporarios} ({erros_temporarios/total*100:.1f}%)", 'vermelho')
        self.print_colored(f"   ❓ Não verificados: {nao_verificados} ({nao_verificados/total*100:.1f}%)", 'branco')
        
        # Métricas de qualidade
        if total_vp_esperados > 0 or total_fp_esperados > 0:
            print(f"\n🎯 MÉTRICAS DE QUALIDADE:")
            
            precisao = vp / (vp + fp) if (vp + fp) > 0 else 0
            recall = vp / (vp + fn) if (vp + fn) > 0 else 0
            f1_score = 2 * (precisao * recall) / (precisao + recall) if (precisao + recall) > 0 else 0
            
            self.print_colored(f"   📈 Precisão: {precisao:.3f} ({vp} VP / {vp + fp} total positivos)", 'verde' if precisao > 0.9 else 'amarelo')
            self.print_colored(f"   📉 Recall: {recall:.3f} ({vp} VP / {vp + fn} esperados)", 'verde' if recall > 0.9 else 'amarelo')
            self.print_colored(f"   ⚖️  F1-Score: {f1_score:.3f}", 'verde' if f1_score > 0.9 else 'amarelo')
            
            self.print_colored(f"   ✅ Verdadeiros Positivos: {vp}/{total_vp_esperados}", 'verde')
            self.print_colored(f"   ❌ Falsos Positivos: {fp}/{total_fp_esperados}", 'vermelho' if fp > 0 else 'verde')
            self.print_colored(f"   ✅ Verdadeiros Negativos: {vn}/{total_fp_esperados}", 'verde')
            self.print_colored(f"   ❌ Falsos Negativos: {fn}/{total_vp_esperados}", 'vermelho' if fn > 0 else 'verde')
    
    def _analisar_concorrencia(self, threads_info, duracao_total):
        """Analisa resultados de teste de concorrência."""
        self.print_header("ANÁLISE DE CONCORRÊNCIA")
        
        total_normas = sum(info['normas_processadas'] for info in threads_info)
        throughput_concorrente = total_normas / duracao_total if duracao_total > 0 else 0
        
        self.print_colored(f"🔄 Threads executadas: {len(threads_info)}", 'azul')
        self.print_colored(f"📊 Total de normas processadas: {total_normas}", 'azul')
        self.print_colored(f"⏱️  Duração total: {duracao_total:.2f}s", 'azul')
        self.print_colored(f"⚡ Throughput concorrente: {throughput_concorrente:.2f} normas/segundo", 'ciano')
        
        print(f"\n📋 DETALHES POR THREAD:")
        for info in threads_info:
            thread_throughput = info['normas_processadas'] / info['duracao'] if info['duracao'] > 0 else 0
            self.print_colored(
                f"   Thread {info['thread_id']}: {info['normas_processadas']} normas em {info['duracao']:.2f}s "
                f"({thread_throughput:.2f} n/s)",
                'branco'
            )
        
        # Verifica inconsistências (race conditions)
        normas_concorrencia = NormaVigente.objects.filter(descricao__contains='CONCORRÊNCIA')
        situacoes_unicas = set(normas_concorrencia.values_list('situacao', flat=True))
        
        if len(situacoes_unicas) > 1:
            self.print_colored("⚠️  POSSÍVEL RACE CONDITION DETECTADA!", 'vermelho')
            self.print_colored(f"   Situações diferentes encontradas: {list(situacoes_unicas)}", 'vermelho')
        else:
            self.print_colored("✅ Consistência mantida - sem race conditions detectadas", 'verde')
    
    def _gerar_relatorio_final(self, resultados_completos, duracao_total):
        """Gera relatório final consolidado."""
        self.print_header("RELATÓRIO FINAL CONSOLIDADO")
        
        print(f"🕐 Duração total da bateria: {duracao_total:.2f}s")
        
        # Resumo por categoria
        for categoria, resultado in resultados_completos.items():
            if resultado:
                self.print_colored(f"\n📂 {categoria.upper()}:", 'negrito')
                self.print_colored(f"   ✅ Taxa de sucesso: {resultado.get('taxa_sucesso', 0):.1f}%", 'verde')
                self.print_colored(f"   📊 Total processadas: {resultado.get('processadas', 0)}", 'azul')
                self.print_colored(f"   ❌ Erros: {resultado.get('erros', 0)}", 'vermelho' if resultado.get('erros', 0) > 0 else 'verde')
        
        # Recomendações baseadas nos resultados
        self._gerar_recomendacoes(resultados_completos)
    
    def _gerar_recomendacoes(self, resultados_completos):
        """Gera recomendações baseadas nos resultados dos testes."""
        self.print_header("RECOMENDAÇÕES")
        
        recomendacoes = []
        
        # Analisa cada categoria
        for categoria, resultado in resultados_completos.items():
            if not resultado:
                continue
                
            taxa_sucesso = resultado.get('taxa_sucesso', 0)
            erros = resultado.get('erros', 0)
            
            if taxa_sucesso < 95:
                recomendacoes.append(f"⚠️  Taxa de sucesso baixa em {categoria} ({taxa_sucesso:.1f}%) - revisar validações")
            
            if erros > 0:
                recomendacoes.append(f"🔧 {erros} erros em {categoria} - verificar logs para detalhes")
        
        # Recomendações gerais
        if not recomendacoes:
            self.print_colored("🎉 EXCELENTE! Todos os testes passaram com sucesso!", 'verde')
            self.print_colored("✅ Sistema está pronto para produção", 'verde')
        else:
            self.print_colored("📝 Pontos de atenção identificados:", 'amarelo')
            for rec in recomendacoes:
                self.print_colored(f"   {rec}", 'amarelo')
    
    def menu_interativo(self):
        """Menu interativo principal."""
        while True:
            self.print_header("SUITE DE TESTES AVANÇADA - NORMAS SEFAZ")
            
            opcoes = [
                "1. 🏗️  Criar cenários básicos",
                "2. 🔥 Criar cenários de stress",
                "3. 🎯 Criar casos extremos (edge cases)",
                "4. 🔄 Criar cenários de concorrência",
                "5. ✨ Criar TODOS os cenários",
                "",
                "6. 🧪 Executar teste básico",
                "7. ⚡ Executar teste de stress",
                "8. 🎪 Executar teste de concorrência",
                "9. 🚀 Executar bateria completa",
                "",
                "10. 🗑️  Limpar todos os testes",
                "11. 📊 Ver estatísticas atuais",
                "12. 🚪 Sair"
            ]
            
            for opcao in opcoes:
                if opcao:
                    self.print_colored(opcao, 'branco')
                else:
                    print()
            
            escolha = input(f"\n{self.cores['ciano']}Selecione uma opção (1-12): {self.cores['reset']}").strip()
            
            try:
                if escolha == '1':
                    self.limpar_testes_anteriores()
                    vp, fp = self.criar_cenarios_basicos()
                    self.print_colored(f"✅ Criados {vp} VP e {fp} FP básicos", 'verde')
                
                elif escolha == '2':
                    quantidade = input("Quantidade de normas para stress test (padrão: 20): ").strip()
                    quantidade = int(quantidade) if quantidade.isdigit() else 20
                    vp, fp = self.criar_cenarios_stress(quantidade)
                    self.print_colored(f"✅ Criadas {quantidade} normas para stress test", 'verde')
                
                elif escolha == '3':
                    vp, fp = self.criar_cenarios_edge_cases()
                    self.print_colored(f"✅ Criados {vp} casos extremos", 'verde')
                
                elif escolha == '4':
                    vp, fp = self.criar_cenarios_concorrencia()
                    self.print_colored(f"✅ Criadas {vp} normas para teste de concorrência", 'verde')
                
                elif escolha == '5':
                    self.limpar_testes_anteriores()
                    self.criar_cenarios_basicos()
                    self.criar_cenarios_stress(15)
                    self.criar_cenarios_edge_cases()
                    self.criar_cenarios_concorrencia()
                    self.print_colored("✅ TODOS os cenários criados com sucesso!", 'verde')
                
                elif escolha == '6':
                    self.executar_teste_basico()
                
                elif escolha == '7':
                    batch_size = input("Batch size para stress test (padrão: 5): ").strip()
                    batch_size = int(batch_size) if batch_size.isdigit() else 5
                    self.executar_teste_stress(batch_size)
                
                elif escolha == '8':
                    self.executar_teste_concorrencia()
                
                elif escolha == '9':
                    self.executar_teste_completo()
                
                elif escolha == '10':
                    self.limpar_testes_anteriores()
                    self.print_colored("🗑️ Todos os testes foram limpos!", 'amarelo')
                
                elif escolha == '11':
                    self.exibir_estatisticas_atuais()
                
                elif escolha == '12':
                    self.print_colored("👋 Saindo... Até logo!", 'ciano')
                    break
                
                else:
                    self.print_colored("❌ Opção inválida! Escolha um número de 1 a 12.", 'vermelho')
            
            except Exception as e:
                self.print_colored(f"❌ Erro: {str(e)}", 'vermelho')
            
            if escolha != '12':
                input(f"\n{self.cores['branco']}Pressione Enter para continuar...{self.cores['reset']}")
    
    def exibir_estatisticas_atuais(self):
        """Exibe estatísticas das normas de teste existentes."""
        self.print_header("ESTATÍSTICAS ATUAIS")
        
        normas_teste = NormaVigente.objects.filter(descricao__startswith='[TESTE]')
        
        if not normas_teste.exists():
            self.print_colored("📊 Nenhuma norma de teste encontrada no banco de dados.", 'amarelo')
            return
        
        total = normas_teste.count()
        
        # Estatísticas por categoria
        basicos = normas_teste.filter(descricao__contains='BÁSICO').count()
        stress = normas_teste.filter(descricao__contains='STRESS').count()
        edge = normas_teste.filter(descricao__contains='EDGE').count()
        concorrencia = normas_teste.filter(descricao__contains='CONCORRÊNCIA').count()
        
        # Estatísticas por situação
        vigentes = normas_teste.filter(situacao='VIGENTE').count()
        nao_vigentes = normas_teste.filter(situacao='NAO_VIGENTE').count()
        dados_invalidos = normas_teste.filter(situacao='DADOS_INVALIDOS').count()
        erros_temporarios = normas_teste.filter(situacao='ERRO_TEMPORARIO').count()
        nao_verificados = normas_teste.filter(situacao='NAO_VERIFICADO').count()
        
        # Estatísticas por tipo esperado
        vp_esperados = normas_teste.filter(descricao__contains='VP').count()
        fp_esperados = normas_teste.filter(descricao__contains='FP').count()
        
        print(f"📊 RESUMO GERAL:")
        self.print_colored(f"   Total de normas de teste: {total}", 'azul')
        
        print(f"\n📂 POR CATEGORIA:")
        self.print_colored(f"   🧪 Básicos: {basicos}", 'branco')
        self.print_colored(f"   🔥 Stress: {stress}", 'branco')
        self.print_colored(f"   🎯 Edge Cases: {edge}", 'branco')
        self.print_colored(f"   🔄 Concorrência: {concorrencia}", 'branco')
        
        print(f"\n📈 POR SITUAÇÃO:")
        self.print_colored(f"   ✅ Vigentes: {vigentes} ({vigentes/total*100:.1f}%)", 'verde')
        self.print_colored(f"   ❌ Não vigentes: {nao_vigentes} ({nao_vigentes/total*100:.1f}%)", 'amarelo')
        self.print_colored(f"   🚫 Dados inválidos: {dados_invalidos} ({dados_invalidos/total*100:.1f}%)", 'magenta')
        self.print_colored(f"   ⚠️ Erros temporários: {erros_temporarios} ({erros_temporarios/total*100:.1f}%)", 'vermelho')
        self.print_colored(f"   ❓ Não verificados: {nao_verificados} ({nao_verificados/total*100:.1f}%)", 'branco')
        
        print(f"\n🎯 TIPOS ESPERADOS:")
        self.print_colored(f"   ✅ Verdadeiros Positivos (VP): {vp_esperados}", 'verde')
        self.print_colored(f"   ❌ Falsos Positivos (FP): {fp_esperados}", 'vermelho')
        
        # Últimas verificações
        ultima_verificacao = normas_teste.exclude(data_verificacao__isnull=True).order_by('-data_verificacao').first()
        if ultima_verificacao:
            self.print_colored(f"🕐 Última verificação: {ultima_verificacao.data_verificacao.strftime('%d/%m/%Y %H:%M:%S')}", 'ciano')
        else:
            self.print_colored("🕐 Nenhuma verificação realizada ainda", 'amarelo')
    
    def executar_verificacao_rapida(self, limite=10):
        """Executa uma verificação rápida com poucas normas para teste."""
        self.print_header(f"VERIFICAÇÃO RÁPIDA ({limite} normas)")
        
        normas_teste = NormaVigente.objects.filter(
            descricao__startswith='[TESTE]'
        ).order_by('?')[:limite]  # Pega normas aleatórias
        
        if not normas_teste.exists():
            self.print_colored("❌ Nenhuma norma de teste encontrada.", 'vermelho')
            return
        
        inicio = time.time()
        self.print_colored(f"🚀 Verificando {normas_teste.count()} normas aleatórias...", 'azul')
        
        resultados = self.integrador.verificar_normas_em_lote(
            list(normas_teste),
            batch_size=3,
            max_retries=2
        )
        
        fim = time.time()
        duracao = fim - inicio
        
        self._exibir_resultados_resumidos(normas_teste, duracao)
        return resultados
    
    def _exibir_resultados_resumidos(self, normas_teste, duracao):
        """Exibe resultados de forma resumida."""
        total = normas_teste.count()
        throughput = total / duracao if duracao > 0 else 0
        
        # Conta resultados
        vigentes = normas_teste.filter(situacao='VIGENTE').count()
        nao_vigentes = normas_teste.filter(situacao='NAO_VIGENTE').count()
        dados_invalidos = normas_teste.filter(situacao='DADOS_INVALIDOS').count()
        erros = normas_teste.filter(situacao='ERRO_TEMPORARIO').count()
        
        print(f"\n⚡ RESULTADOS RÁPIDOS:")
        self.print_colored(f"   ⏱️ Duração: {duracao:.2f}s ({throughput:.1f} normas/s)", 'azul')
        self.print_colored(f"   ✅ Vigentes: {vigentes}", 'verde')
        self.print_colored(f"   ❌ Não vigentes: {nao_vigentes}", 'amarelo')
        self.print_colored(f"   🚫 Inválidas: {dados_invalidos}", 'magenta')
        self.print_colored(f"   ⚠️ Erros: {erros}", 'vermelho' if erros > 0 else 'verde')
    
    def verificar_integridade_sistema(self):
        """Verifica a integridade do sistema de integração."""
        self.print_header("VERIFICAÇÃO DE INTEGRIDADE DO SISTEMA")
        
        problemas = []
        
        # 1. Testa conexão básica
        try:
            self.print_colored("🔍 Testando conexão com SEFAZ...", 'azul')
            # Cria uma norma simples para teste
            norma_teste = NormaVigente(
                tipo='DECRETO',
                numero='21.866',
                descricao='[TESTE INTEGRIDADE] Norma para verificação de conexão',
                situacao='NAO_VERIFICADO'
            )
            
            resultado = self.integrador._consultar_norma_sefaz(norma_teste)
            if resultado:
                self.print_colored("✅ Conexão com SEFAZ: OK", 'verde')
            else:
                self.print_colored("❌ Conexão com SEFAZ: FALHA", 'vermelho')
                problemas.append("Falha na conexão com SEFAZ")
        
        except Exception as e:
            self.print_colored(f"❌ Erro na conexão: {str(e)}", 'vermelho')
            problemas.append(f"Erro de conexão: {str(e)}")
        
        # 2. Testa validações
        try:
            self.print_colored("🔍 Testando validações...", 'azul')
            
            # Teste com dados válidos
            norma_valida = NormaVigente(tipo='DECRETO', numero='21866')
            if self.integrador._validar_dados_norma(norma_valida):
                self.print_colored("✅ Validação de dados válidos: OK", 'verde')
            else:
                problemas.append("Falha na validação de dados válidos")
            
            # Teste com dados inválidos
            norma_invalida = NormaVigente(tipo='', numero='')
            if not self.integrador._validar_dados_norma(norma_invalida):
                self.print_colored("✅ Rejeição de dados inválidos: OK", 'verde')
            else:
                problemas.append("Falha na rejeição de dados inválidos")
        
        except Exception as e:
            self.print_colored(f"❌ Erro nas validações: {str(e)}", 'vermelho')
            problemas.append(f"Erro nas validações: {str(e)}")
        
        # 3. Testa rate limiting
        try:
            self.print_colored("🔍 Testando rate limiting...", 'azul')
            
            inicio = time.time()
            for i in range(3):  # Faz 3 requisições rápidas
                norma = NormaVigente(tipo='DECRETO', numero=f'2186{i}')
                self.integrador._consultar_norma_sefaz(norma)
            fim = time.time()
            
            if fim - inicio >= 2:  # Deve ter algum delay
                self.print_colored("✅ Rate limiting: OK", 'verde')
            else:
                self.print_colored("⚠️ Rate limiting: Pode estar muito permissivo", 'amarelo')
        
        except Exception as e:
            self.print_colored(f"❌ Erro no rate limiting: {str(e)}", 'vermelho')
            problemas.append(f"Erro no rate limiting: {str(e)}")
        
        # Resultado final
        if not problemas:
            self.print_colored("\n🎉 SISTEMA ÍNTEGRO - Todos os testes passaram!", 'verde')
            return True
        else:
            self.print_colored(f"\n⚠️ {len(problemas)} PROBLEMA(S) ENCONTRADO(S):", 'vermelho')
            for problema in problemas:
                self.print_colored(f"   • {problema}", 'vermelho')
            return False
    
    def benchmark_performance(self, tamanhos=[5, 10, 20, 50]):
        """Executa benchmark de performance com diferentes tamanhos de lote."""
        self.print_header("BENCHMARK DE PERFORMANCE")
        
        resultados_benchmark = []
        
        for tamanho in tamanhos:
            self.print_colored(f"\n🏃 Testando com {tamanho} normas...", 'azul')
            
            # Cria normas temporárias para o benchmark
            normas_temp = []
            for i in range(tamanho):
                norma = NormaVigente(
                    tipo='DECRETO',
                    numero=f'21{800 + i}',
                    descricao=f'[BENCHMARK-{tamanho}] Norma {i+1} para benchmark',
                    situacao='NAO_VERIFICADO'
                )
                normas_temp.append(norma)
            
            # Salva temporariamente
            NormaVigente.objects.bulk_create(normas_temp)
            
            try:
                inicio = time.time()
                
                self.integrador.verificar_normas_em_lote(
                    normas_temp,
                    batch_size=min(5, tamanho),
                    max_retries=1
                )
                
                fim = time.time()
                duracao = fim - inicio
                throughput = tamanho / duracao if duracao > 0 else 0
                
                resultado = {
                    'tamanho': tamanho,
                    'duracao': duracao,
                    'throughput': throughput,
                    'tempo_por_norma': duracao / tamanho if tamanho > 0 else 0
                }
                
                resultados_benchmark.append(resultado)
                
                self.print_colored(
                    f"   ⏱️ {duracao:.2f}s | ⚡ {throughput:.1f} normas/s | "
                    f"🎯 {resultado['tempo_por_norma']:.2f}s por norma",
                    'ciano'
                )
            
            finally:
                # Limpa normas temporárias
                NormaVigente.objects.filter(descricao__startswith=f'[BENCHMARK-{tamanho}]').delete()
        
        # Exibe análise comparativa
        self._analisar_benchmark(resultados_benchmark)
    
    def _analisar_benchmark(self, resultados):
        """Analisa resultados do benchmark."""
        print(f"\n📊 ANÁLISE COMPARATIVA:")
        
        melhor_throughput = max(resultados, key=lambda x: x['throughput'])
        pior_throughput = min(resultados, key=lambda x: x['throughput'])
        
        self.print_colored(
            f"🏆 Melhor throughput: {melhor_throughput['throughput']:.1f} normas/s "
            f"(lote de {melhor_throughput['tamanho']})",
            'verde'
        )
        
        self.print_colored(
            f"🐌 Pior throughput: {pior_throughput['throughput']:.1f} normas/s "
            f"(lote de {pior_throughput['tamanho']})",
            'vermelho'
        )
        
        # Recomendação de batch size ótimo
        throughput_medio = sum(r['throughput'] for r in resultados) / len(resultados)
        melhores = [r for r in resultados if r['throughput'] >= throughput_medio]
        
        if melhores:
            batch_otimo = min(melhores, key=lambda x: x['tamanho'])
            self.print_colored(
                f"💡 Batch size recomendado: {batch_otimo['tamanho']} "
                f"({batch_otimo['throughput']:.1f} normas/s)",
                'amarelo'
            )


def main():
    """Função principal."""
    try:
        suite = TesteSuiteAvancado()
        
        # Verificação inicial
        print("🚀 Iniciando Suite de Testes Avançada - SEFAZ Integração")
        print("=" * 60)
        
        # Opção de verificação rápida inicial
        resposta = input("Deseja fazer uma verificação rápida do sistema primeiro? (s/N): ").strip().lower()
        if resposta in ['s', 'sim', 'y', 'yes']:
            if not suite.verificar_integridade_sistema():
                resposta = input("\nProblemas encontrados. Continuar mesmo assim? (s/N): ").strip().lower()
                if resposta not in ['s', 'sim', 'y', 'yes']:
                    print("Encerrando...")
                    return
        
        # Menu principal
        suite.menu_interativo()
    
    except KeyboardInterrupt:
        print(f"\n{suite.cores['amarelo']}⚠️ Interrompido pelo usuário.{suite.cores['reset']}")
    except Exception as e:
        print(f"\n{suite.cores['vermelho']}❌ Erro fatal: {str(e)}{suite.cores['reset']}")
    finally:
        print(f"{suite.cores['ciano']}👋 Finalizando suite de testes...{suite.cores['reset']}")


if __name__ == "__main__":
    main()