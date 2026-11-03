"""用户表数据访问；只访问 user_db，禁止跨库查询。

事务边界约定：本层**不提交事务**，只做 `add + flush`，由 service 层决定
commit / rollback。原因见 `docs/api-contract/user-service.md` 第 0 节：
注册要同时写 `t_user` / `t_points_account` / `t_points_log` 三张表，
扣分要同时写账户与流水，必须整体成功或整体回滚，不能出现半成功状态。
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import User


class UserRepository:
    """`t_user` 的读写；所有查询默认过滤 `is_deleted=0`。"""

    def find_by_id(self, db: Session, user_id: int) -> User | None:
        statement = select(User).where(User.id == user_id, User.is_deleted == 0)
        return db.scalar(statement)

    def find_by_username(self, db: Session, username: str) -> User | None:
        statement = select(User).where(
            User.username == username, User.is_deleted == 0
        )
        return db.scalar(statement)

    def exists_username(self, db: Session, username: str) -> bool:
        """未删除范围内用户名是否已存在（唯一索引的业务层前置检查）。"""

        statement = select(func.count(User.id)).where(
            User.username == username, User.is_deleted == 0
        )
        return bool(db.scalar(statement))

    def add(self, db: Session, user: User) -> User:
        """插入用户并 flush 拿到自增主键；不 commit，由 service 决定事务。"""

        db.add(user)
        db.flush()
        return user

    def search(
        self,
        db: Session,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[User], int]:
        """运营后台的用户检索；按 id 升序，便于稳定翻页。"""

        from sqlalchemy import func, or_, select

        conditions: list[object] = [User.is_deleted == 0]
        if keyword:
            like = f"%{keyword}%"
            # P5：排行里只有"用户 #663"，运营要能直接按 ID 搜到人；
            # 纯数字关键字同时匹配 ID 与用户名/昵称，不牺牲原有模糊搜索。
            matches = [User.username.like(like), User.nickname.like(like)]
            if keyword.isdigit():
                matches.append(User.id == int(keyword))
            conditions.append(or_(*matches))
        if status:
            conditions.append(User.status == status)
        total = db.scalar(select(func.count(User.id)).where(*conditions)) or 0
        rows = db.scalars(
            select(User)
            .where(*conditions)
            .order_by(User.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        return list(rows), total

    def update_fields(self, db: Session, user: User, values: dict[str, object]) -> User:
        """按字段名更新；values 应来自 model_dump(exclude_unset=True)。"""

        for field, value in values.items():
            setattr(user, field, value)
        db.flush()
        return user


user_repository = UserRepository()
