"""领域错误类型。"""


class DomainError(ValueError):
    """所有领域规则违例的基类。"""


class ValidationError(DomainError):
    """信封或载荷不符合合同。"""

    def __init__(self, errors):
        self.errors = list(errors)
        super().__init__("; ".join(self.errors))


class ConflictError(DomainError):
    """事件与既有事实冲突（重复编号、非法状态迁移等）。"""
