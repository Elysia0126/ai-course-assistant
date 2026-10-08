import { redirect } from "next/navigation";

export default async function CourseIndexPage({ params }: PageProps<"/courses/[courseId]">) {
  const { courseId } = await params;
  redirect(`/courses/${courseId}/materials`);
}
