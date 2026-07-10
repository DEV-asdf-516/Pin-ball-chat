class Singleton:
    # 서브클래스마다 독립적인 인스턴스 하나만 만드는 __new__ 믹스인.
    # cls._instance 대입은 항상 실제 서브클래스(cls) 자신에 대해 일어나므로,
    # 이 베이스에 한 번만 정의해도 서브클래스별로 싱글턴이 분리된다.

    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
