export type Transaction = {
  branch_id: string;
  date: string;
  type: string;
  category_id: string | null;
  category_name: string | null;
  item_name: string | null;
  amount: number;
  payment_method: string | null;
  source: string;
  verified_by_user_id: string | null;
  created_at: string;
};
