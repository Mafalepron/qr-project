import uvicorn
import os
import sys

print("--- [DEBUG] Starting run_server.py ---")
print(f"--- [DEBUG] Python executable: {sys.executable}")

if __name__ == "__main__":
    print("--- [DEBUG] Inside __main__ block ---")
    
    # Проверяем, есть ли файл .env и загружаем переменные, если нужно
    # Это полезно, если в будущем конфигурация порта/хоста будет в .env
    if os.path.exists(".env"):
        print("--- [DEBUG] .env file found, loading variables. ---")
        from dotenv import load_dotenv
        load_dotenv()

    # Получаем порт и хост из переменных окружения или используем значения по умолчанию
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    
    print(f"--- [DEBUG] Starting uvicorn on {host}:{port} with reload=True ---")
    
    uvicorn.run(
        "backend.app.main:app",
        host=host,
        port=port,
        reload=True
    )
    
    print("--- [DEBUG] This should not be printed if server runs correctly ---")

print("--- [DEBUG] Script finished ---") 