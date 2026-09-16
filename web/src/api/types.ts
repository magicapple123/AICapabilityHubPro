/** 统一响应结构：所有接口都返回四字段 Result（指南 5.1）。 */
export interface Result<T> {
  code: number
  message: string
  data: T | null
  requestId: string
}

/** 分页 data：list / total / page / page_size（指南 5.1）。 */
export interface PageData<T> {
  list: T[]
  total: number
  page: number
  page_size: number
}

/** 不分页的列表 data：list / total。 */
export interface ListData<T> {
  list: T[]
  total: number
}

export interface LoginPayload {
  username: string
  password: string
}

/** user-service 登录出参；`username` 为契约字段，`user_name` 兼容旧字段。 */
export interface LoginData {
  token: string
  token_type?: string
  expire_at?: string
  user_id?: number | string
  username?: string
  user_name?: string
}

export interface RegisterPayload {
  username: string
  password: string
  nickname?: string
}

/** 注册即建积分账户并赠送初始积分（user-service 契约第 2 节）。 */
export interface RegisterData {
  user_id: number
  username: string
  nickname: string
  balance: number
  initial_points: number
}
