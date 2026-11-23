// Author: Codex (IIC)
#include <chrono>
#include <cstring>
#include <iostream>
#include <opencv2/core.hpp>
#include <opencv2/videoio.hpp>
#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/image.hpp>

int main(int argc, char **argv) {
    rclcpp::init(argc, argv);
    rclcpp::NodeOptions options;
    options.enable_rosout(false).start_parameter_services(false).start_parameter_event_publisher(false);
    auto node = std::make_shared<rclcpp::Node>("unitree_front_color_bridge", options);
    auto pub = node->create_publisher<sensor_msgs::msg::Image>(
        "/g1/unitree_front/color/image_raw", rclcpp::SensorDataQoS().keep_last(1));
    cv::VideoCapture video("pipe:0", cv::CAP_FFMPEG);
    if (!video.isOpened()) {
        std::cerr << "Could not open live H.264 input" << std::endl;
        return 1;
    }
    cv::Mat frame;
    using Clock = std::chrono::steady_clock;
    auto next_publish = Clock::now();
    auto next_status = next_publish;
    uint64_t decoded = 0, published = 0;
    while (rclcpp::ok() && video.read(frame)) {
        const auto now = Clock::now();
        if (frame.type() != CV_8UC3 || frame.empty()) {
            std::cerr << "Unexpected decoded frame type" << std::endl;
            return 1;
        }
        ++decoded;
        if (now < next_publish) continue;
        next_publish = now + std::chrono::milliseconds(180);
        sensor_msgs::msg::Image msg;
        msg.header.stamp = node->now();
        msg.header.frame_id = "unitree_front_video";
        msg.height = frame.rows;
        msg.width = frame.cols;
        msg.encoding = "bgr8";
        msg.step = msg.width * 3;
        msg.data.resize(msg.step * msg.height);
        for (int row = 0; row < frame.rows; ++row) {
            std::memcpy(msg.data.data() + row * msg.step, frame.ptr(row), msg.step);
        }
        pub->publish(msg);
        ++published;
        if (now >= next_status) {
            std::cerr << "decoded=" << decoded << " published=" << published << " geometry="
                      << msg.width << "x" << msg.height << " stamps=decoder_host_time" << std::endl;
            next_status = now + std::chrono::seconds(60);
        }
    }
    video.release();
    rclcpp::shutdown();
    return 0;
}
