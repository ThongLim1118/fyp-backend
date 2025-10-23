import subprocess, shlex, json
from pathlib import Path
from typing import List, Optional

class FT:
    def __init__(self, userdir: str, config: str, python_bin: str = "python"):
        self.userdir = userdir
        self.config = config
        self.python_bin = python_bin

    def _base(self):
        # 等价于：python -m freqtrade --userdir ... -c ...
        print("self.python_bin:", repr(self.python_bin))
        print("self.userdir:", repr(self.userdir)) 
        print("self.config:", repr(self.config))
        return [self.python_bin, "-m", "freqtrade"]

    def _run(self, args: List[str], timeout: Optional[int] = None):
        cmd = self._base() + args + ["--userdir", self.userdir, "-c", self.config]
        print(">>", " ".join(map(shlex.quote, cmd)))
        cp = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout)
        if cp.returncode != 0:
            raise RuntimeError(cp.stderr or cp.stdout)
        return cp.stdout

    def download_data(self, pairs: List[str], timeframe: str, timerange: str):
        return self._run(["download-data", "--pairs", ",".join(pairs), "--timeframe", timeframe, "--timerange", timerange])

    def backtest(self, strategy: str, pairs: List[str], timeframe: str,
                 timerange: Optional[str] = None, export: Optional[str] = None, strategy_path: str | None = None) -> dict:
        args = ["backtesting", "-s", strategy,
                "--pairs", ",".join(pairs), "--timeframe", timeframe,
                "--export-filename", "bt_result.json"]
        if strategy_path: args += ["--strategy-path", strategy_path]
        if timerange: args += ["--timerange", timerange]
        if export:    args += ["--export", export]            # "trades" / "signals" / "none"
        out = self._run(args)
        # 读取导出的结果文件（路径按你的 config/exportpath 设置来）
        p = Path(self.userdir) / "backtest_results" / "bt_result.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"stdout": out}

    def hyperopt(self, strategy: str, pairs: List[str], timeframe: str,
                 epochs: int = 50, spaces: Optional[List[str]] = None) -> str:
        args = ["hyperopt", "-s", strategy, "--pairs", ",".join(pairs),
                "--timeframe", timeframe, "--epochs", str(epochs)]
        if spaces:
            for sp in spaces: args += ["--spaces", sp]        # 例如 ["buy","sell"]
        return self._run(args)

    def list_available_pairs(self, exchange: str, quote: str) -> list[str]:
        # 1. Construct the list-pairs command arguments
        # Note: We keep the command structure correct as learned previously
        command_args = [
            "list-pairs", 
            "--exchange", exchange, 
            "--quote", quote,
        ]
        
        # 2. Run the command using your existing _run method
        # The _run method will handle the 'python -m freqtrade --userdir ...' prefix
        result_text = self._run(command_args) # Assuming _run returns the full stdout
        
        # 3. Parse the result to get the list of pairs
        available_pairs = self._parse_pairs_output(result_text, quote)
        
        return available_pairs
    
    def _parse_pairs_output(self, output: str, quote: str) -> list[str]:
        """Parses the output of 'freqtrade list-pairs' to return a list of valid pairs."""
        pairs = []
        # The output usually contains a table. We only care about lines starting with a pair.
        # A common pattern is lines that contain the quote currency and have a certain structure.
        
        for line in output.splitlines():
            line = line.strip()
            
            # Look for lines that contain the quote and a forward slash, 
            # and ignore headers/footers/info messages.
            if f'/{quote}' in line and not line.startswith(('Pair', '---', 'INFO', 'WARNING')):
                
                # The pair is often the first word/token on the line (e.g., "ETH/USDT" [1.00])
                try:
                    # Extract the pair, typically the first element
                    pair = line.split()[0] 
                    
                    # Basic validation
                    if '/' in pair and pair.endswith(f'/{quote}'):
                        pairs.append(pair)
                except IndexError:
                    # Ignore malformed lines
                    continue
                    
        return pairs

############# 调用示例 ###########
# ft = FT(userdir="/user_data", config="/user_data/config.json")

# # 下数据
# ft.download_data(["BTCUSDT","ETHUSDT"], "1h")

# # 回测（读取 bt_result.json）
# result = ft.backtest(strategy="ma_rsi", pairs=["BTCUSDT"], timeframe="1h",
#                      timerange="20240101-20241001", export="trades")
# print(result)

# # 超参
# log = ft.hyperopt(strategy="ma_rsi", pairs=["BTCUSDT"], timeframe="1h",
#                   epochs=80, spaces=["buy","sell"])
# print(log[:600])