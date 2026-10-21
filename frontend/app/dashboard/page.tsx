import { redirect } from "next/navigation";

// The overview now lives on the home page.
export default function Dashboard() {
  redirect("/");
}
