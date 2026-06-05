import os
import json
from src.domain.models import AnalysisRequest, AnalysisType
from src.services.llm_analyzer import LLMAnalyzer
from src.services.analysis_orchestrator import AnalysisOrchestrator

def main():
    print("=== Запуск LLM-Orchestrated Analysis Engine ===")
    
    # Инициализируем LLMAnalyzer.
    # Если в переменной окружения нет GROQ_API_KEY, автоматически включится Mock-режим.
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        print("[Инфо] Переменная GROQ_API_KEY не найдена. Запуск в MOCK-режиме.")
        analyzer = LLMAnalyzer(api_key="mock")
    else:
        print(f"[Инфо] Переменная GROQ_API_KEY обнаружена. Запуск в реальном режиме с Groq API.")
        analyzer = LLMAnalyzer(api_key=api_key)
        
    orchestrator = AnalysisOrchestrator(analyzer)

    # Создаем запрос на многоэтапный анализ (Безопасность + Качество кода + Производительность)
    print("\n[1/3] Подготовка запроса для анализа...")
    request = AnalysisRequest(
        text="""
def process_user_data(user_id, input_query):
    # Уязвимость SQL-инъекции
    query = "SELECT * FROM users WHERE id = " + user_id
    db.execute(query)
    
    # Квадратичный цикл
    results = []
    for x in range(1000):
        for y in range(1000):
            results.append(x * y)
            
    return results
""",
        analysis_type=AnalysisType.SECURITY,
        parameters={"extra_types": ["code_quality", "performance"]}
    )

    print("[2/3] Выполнение анализа (Оркестратор координирует стадии)...")
    try:
        result = orchestrator.execute_analysis(request)
        
        print("[3/3] Анализ успешно завершен! Результаты:\n")
        # Выводим отформатированный результат
        print(json.dumps(result.model_dump(), indent=2, ensure_ascii=False))
        
    except Exception as e:
        print(f"[Ошибка] Во время анализа произошла ошибка: {e}")

if __name__ == "__main__":
    main()
