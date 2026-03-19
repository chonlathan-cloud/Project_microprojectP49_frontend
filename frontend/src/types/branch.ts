export type Branch = {
  id: string;
  name: string;
  type: "COFFEE" | "RESTAURANT";
};

export type BranchListResponse = {
  branches: Branch[];
};
