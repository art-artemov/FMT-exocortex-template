"""
Конфигурация pytest для тестов scripts/.

Решает проблему дефиса в имени agent-dashboard.py (невалидный Python-идентификатор):
загружает модуль через importlib.util.spec_from_file_location и регистрирует
его в sys.modules как "agent_dashboard".
"""
import importlib.util
import sys
from pathlib import Path

script_path = Path(__file__).parent.parent / "agent-dashboard.py"
spec = importlib.util.spec_from_file_location("agent_dashboard", script_path)
module = importlib.util.module_from_spec(spec)
sys.modules["agent_dashboard"] = module
spec.loader.exec_module(module)
