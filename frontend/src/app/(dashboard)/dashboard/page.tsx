import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export default function DashboardPage() {
  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Overview</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-slate-600">
            Dashboard foundation is ready. Next prompts can now plug in analytics,
            upload, and POS data flows.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
