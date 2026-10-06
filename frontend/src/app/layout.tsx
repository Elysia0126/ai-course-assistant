import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { Toaster } from "sonner";

import { AppHeader } from "@/components/app-header";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: { default: "AI Course Assistant", template: "%s · AI Course Assistant" },
  description: "Upload lecture slides and notes, then ask cited questions, take quizzes and study flashcards.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}>
      <body className="flex min-h-full flex-col font-sans">
        <AppHeader />
        <main className="flex flex-1 flex-col">{children}</main>
        <Toaster richColors position="bottom-right" closeButton />
      </body>
    </html>
  );
}
