from abc import ABC, abstractmethod
class SizerBase(ABC):
    """
    所有 Sizer 的基底類別，規則
    """
    @abstractmethod
    def get_size(self, signal, account, position_manager, row):
        """
        回傳要下的最終口數（正整數或 0)
        signal  : 策略訊號(BUY / SELL / EXIT)
        account : Account 物件（用來檢查資金）
        position_manager : PM 物件（看是否持倉）
        row     : 當前 K 棒資料
        回傳值   : tuple (qty, leverage)
        """
        pass
