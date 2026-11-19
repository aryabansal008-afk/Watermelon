"use client";
import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { useGSAP } from "@gsap/react";

gsap.registerPlugin(useGSAP, ScrollTrigger);
export { gsap, useGSAP, ScrollTrigger };

/** Motion preferences are matched by each scoped animation; this helper keeps
 * route transitions and feature reveals on the same reduced-motion policy. */
export const motionPreference = "(prefers-reduced-motion: no-preference)";
