import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { Toaster } from "sonner";

import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: { default: "AI Course Assistant", template: "%s · AI Course Assistant" },
  description: "Upload lecture slides and notes, then ask cited questions, take quizzes and study flashcards.",
};

// The header and <main> come from the route groups: (app) for signed-in pages, (auth) for sign-in pages.
export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}>
      <body className="flex min-h-full flex-col font-sans">
        {children}
        <Toaster richColors position="bottom-right" closeButton />
      </body>
    </html>
  );
}
